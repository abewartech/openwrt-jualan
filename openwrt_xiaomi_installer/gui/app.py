"""
gui/app.py
==========
Main tkinter application for the OpenWRT Xiaomi Installer.

Features:
  • Dark mode UI (DarkTheme from gui.widgets)
  • Router model selection (auto / 4A V1 / 4A V2 / 4C)
  • IP address entry with auto-detection
  • Network adapter dropdown (Windows NIC detection)
  • Options: backup-only, no-backup, force, verbose
  • Start / Stop button
  • 7-step progress bar
  • Real-time coloured log viewer
  • Separate thread for installation (keeps GUI responsive)
  • Recovery / MiWifi Tool button
"""

from __future__ import annotations

import logging
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

from gui.widgets import DarkTheme as T, LogViewer, ProgressSection, SectionFrame

# ─────────────────────────────────────────────────────────────────────────────
# GUI-compatible logging handler
# ─────────────────────────────────────────────────────────────────────────────

class QueueLogHandler(logging.Handler):
    """Push log records into a thread-safe queue consumed by the GUI."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.queue.put((record.levelname, msg))
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# InstallerApp
# ─────────────────────────────────────────────────────────────────────────────

class InstallerApp(tk.Tk):
    """
    Main application window.

    Layout:
      ┌───────────────────────────────────────────┐
      │ Header (title + version)                  │
      ├───────────────────────────────────────────┤
      │ [Config panel]   [Network adapter panel]  │
      ├───────────────────────────────────────────┤
      │ Options checkboxes                        │
      ├───────────────────────────────────────────┤
      │ Progress section                          │
      ├───────────────────────────────────────────┤
      │ Log viewer (scrollable)                   │
      ├───────────────────────────────────────────┤
      │ [Start] [Backup Only] [Recovery] [Clear]  │
      └───────────────────────────────────────────┘
    """

    APP_TITLE   = "OpenWRT Xiaomi Installer"
    APP_VERSION = "1.0.0"
    MIN_W, MIN_H = 860, 680

    MODEL_OPTIONS = {
        "Auto-detect":                 "auto",
        "4A Gigabit V1 (fw < 2.30.20)": "4a_v1",
        "4A Gigabit V2 (fw ≥ 2.30.20)": "4a_v2",
        "Mi Router 4C":                "4c",
    }

    def __init__(self):
        super().__init__()
        self.title(self.APP_TITLE)
        self.minsize(self.MIN_W, self.MIN_H)
        self.resizable(True, True)
        self.configure(bg=T.BG)

        # Threading
        self._log_queue: queue.Queue = queue.Queue()
        self._install_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._setup_style()
        self._setup_icon()
        self._build_ui()
        self._attach_log_handler()
        self._start_log_poll()
        self._detect_adapters()
        self._auto_detect_ip()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        T.configure_ttk(style)

    def _setup_icon(self) -> None:
        try:
            # Try to set a simple coloured icon via PhotoImage
            img = tk.PhotoImage(data=(
                "R0lGODlhEAAQAIABAAAAAP///yH5BAEKAAEALAAAAAAQABAAAAIjjI+py+0Po5y02ouz"
                "3rz7D4biSJbmiabqyrbuC8fyTNf2UQAAOw=="
            ))
            self.iconphoto(True, img)
        except Exception:
            pass

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=T.BG2, pady=12)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="⚡  OpenWRT Xiaomi Auto-Installer",
            bg=T.BG2, fg=T.ACCENT,
            font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(side=tk.LEFT, padx=20)

        tk.Label(
            header,
            text=f"v{self.APP_VERSION}  │  Supports: 4A Gigabit V1/V2  •  4C",
            bg=T.BG2, fg=T.TEXT_MUTED,
            font=(T.FONT_FAMILY, T.FONT_SMALL),
        ).pack(side=tk.RIGHT, padx=20)

        # ── Main content ──────────────────────────────────────────────────────
        main = tk.Frame(self, bg=T.BG)
        main.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        # Top row: Config + Network
        top_row = tk.Frame(main, bg=T.BG)
        top_row.pack(fill=tk.X, pady=(0, 8))

        self._build_config_panel(top_row)
        self._build_network_panel(top_row)

        # Options row
        self._build_options_panel(main)

        # Progress
        prog_frame = SectionFrame(main, "Installation Progress")
        prog_frame.pack(fill=tk.X, pady=(0, 8))
        self._progress = ProgressSection(prog_frame)
        self._progress.pack(fill=tk.X)

        # Log viewer
        log_frame = SectionFrame(main, "Activity Log")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self._log_viewer = LogViewer(log_frame)
        self._log_viewer.pack(fill=tk.BOTH, expand=True)

        # Button bar
        self._build_button_bar(main)

    def _build_config_panel(self, parent) -> None:
        frame = SectionFrame(parent, "Router Configuration")
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        frame.columnconfigure(1, weight=1)

        # Model
        ttk.Label(frame, text="Model:").grid(row=0, column=0, sticky="w", pady=3)
        self._model_var = tk.StringVar(value="Auto-detect")
        model_cb = ttk.Combobox(
            frame,
            textvariable=self._model_var,
            values=list(self.MODEL_OPTIONS.keys()),
            state="readonly", width=28,
        )
        model_cb.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)

        # Router IP
        ttk.Label(frame, text="Router IP:").grid(row=1, column=0, sticky="w", pady=3)
        self._ip_var = tk.StringVar(value="192.168.31.1")
        ttk.Entry(frame, textvariable=self._ip_var, width=20).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=3
        )

        # OpenWRT IP
        ttk.Label(frame, text="OpenWRT IP:").grid(row=2, column=0, sticky="w", pady=3)
        self._openwrt_ip_var = tk.StringVar(value="192.168.1.1")
        ttk.Entry(frame, textvariable=self._openwrt_ip_var, width=20).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=3
        )

        # Admin password
        ttk.Label(frame, text="Admin Password:").grid(row=3, column=0, sticky="w", pady=3)
        self._password_var = tk.StringVar()
        pw_entry = ttk.Entry(frame, textvariable=self._password_var, show="•", width=20)
        pw_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(frame, text="(leave blank to auto-try)", foreground=T.TEXT_MUTED,
                  font=(T.FONT_FAMILY, T.FONT_SMALL)).grid(
            row=4, column=1, sticky="w", padx=(8, 0))

    def _build_network_panel(self, parent) -> None:
        frame = SectionFrame(parent, "Network Adapter")
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        # Adapter dropdown
        self._adapter_var = tk.StringVar(value="Detecting…")
        self._adapter_cb = ttk.Combobox(
            frame, textvariable=self._adapter_var, state="readonly"
        )
        self._adapter_cb.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(
            frame, text="↺  Refresh Adapters",
            command=self._detect_adapters,
        ).pack(fill=tk.X, pady=(0, 4))

        ttk.Button(
            frame, text="🔍  Auto-detect Router IP",
            command=self._auto_detect_ip,
        ).pack(fill=tk.X, pady=(0, 4))

        # Adapter info label
        self._adapter_info_var = tk.StringVar(value="")
        ttk.Label(
            frame, textvariable=self._adapter_info_var,
            foreground=T.TEXT_MUTED,
            font=(T.FONT_FAMILY, T.FONT_SMALL),
            wraplength=250,
        ).pack(anchor="w", pady=(4, 0))

    def _build_options_panel(self, parent) -> None:
        frame = SectionFrame(parent, "Options")
        frame.pack(fill=tk.X, pady=(0, 8))

        opts_row = tk.Frame(frame, bg=T.BG3)
        opts_row.pack(fill=tk.X)

        self._backup_only_var = tk.BooleanVar()
        self._no_backup_var   = tk.BooleanVar()
        self._force_var       = tk.BooleanVar()
        self._verbose_var     = tk.BooleanVar()

        def chk(text, var, fg=T.TEXT):
            return ttk.Checkbutton(opts_row, text=text, variable=var,
                                   style="TCheckbutton")

        chk("Backup Only (no flash)", self._backup_only_var).pack(side=tk.LEFT, padx=12)
        chk("Skip Backup ⚠",          self._no_backup_var).pack(side=tk.LEFT, padx=12)
        chk("Force / Re-download",    self._force_var).pack(side=tk.LEFT, padx=12)
        chk("Verbose Logging",        self._verbose_var).pack(side=tk.LEFT, padx=12)

    def _build_button_bar(self, parent) -> None:
        bar = tk.Frame(parent, bg=T.BG)
        bar.pack(fill=tk.X, pady=(0, 4))

        self._start_btn = ttk.Button(
            bar, text="▶  Start Installation",
            style="Accent.TButton",
            command=self._on_start,
        )
        self._start_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._backup_btn = ttk.Button(
            bar, text="💾  Backup Only",
            command=self._on_backup_only,
        )
        self._backup_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            bar, text="🛠  Recovery Tools",
            command=self._on_recovery,
        ).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(
            bar, text="🗑  Clear Log",
            command=self._log_viewer.clear,
        ).pack(side=tk.LEFT, padx=(0, 8))

        self._stop_btn = ttk.Button(
            bar, text="■  Stop",
            style="Danger.TButton",
            command=self._on_stop,
            state=tk.DISABLED,
        )
        self._stop_btn.pack(side=tk.RIGHT)

    # ── Adapter detection ─────────────────────────────────────────────────────

    def _detect_adapters(self) -> None:
        """Enumerate NICs and populate the adapter Combobox."""
        try:
            from utils.network_windows import list_adapters, find_router_adapter
            adapters = list_adapters()
            self._adapters = adapters
            labels = []
            selected_idx = 0
            router_adapter = find_router_adapter(self._ip_var.get(), adapters)
            for i, a in enumerate(adapters):
                ip_str = a.ip_addresses[0] if a.ip_addresses else "no IP"
                label  = f"{a.name}  [{ip_str}]"
                labels.append(label)
                if router_adapter and a.name == router_adapter.name:
                    selected_idx = i

            if labels:
                self._adapter_cb.configure(values=labels)
                self._adapter_cb.current(selected_idx)
                info = adapters[selected_idx]
                self._adapter_info_var.set(
                    info.description or info.name
                )
            else:
                self._adapter_cb.configure(values=["No adapters found"])
                self._adapter_cb.current(0)
        except Exception as exc:
            self._adapter_cb.configure(values=[f"Error: {exc}"])
            self._adapter_cb.current(0)

    def _auto_detect_ip(self) -> None:
        """Try to detect the router IP from the active NIC."""
        try:
            from utils.network_windows import get_local_ip_for_router
            local_ip = get_local_ip_for_router(self._ip_var.get())
            if local_ip and local_ip != "0.0.0.0":
                # Router is likely at .1 of the same subnet
                parts = local_ip.rsplit(".", 1)
                guess = parts[0] + ".1"
                self._ip_var.set(guess)
                self._log("INFO", f"Auto-detected router IP: {guess}")
        except Exception:
            pass

    # ── Logging ───────────────────────────────────────────────────────────────

    def _attach_log_handler(self) -> None:
        """Attach QueueLogHandler to the root app logger."""
        handler = QueueLogHandler(self._log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                               datefmt="%H:%M:%S"))
        logging.getLogger("openwrt_installer").addHandler(handler)
        logging.getLogger("openwrt_installer").setLevel(logging.DEBUG)

    def _start_log_poll(self) -> None:
        """Poll the log queue every 100 ms and update LogViewer."""
        self._drain_log_queue()
        self.after(100, self._start_log_poll)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                level, msg = self._log_queue.get_nowait()
                self._log_viewer.append(msg, level)
        except queue.Empty:
            pass

    def _log(self, level: str, msg: str) -> None:
        """Directly add a message to the log viewer."""
        self._log_viewer.append(msg, level)

    # ── Installation thread ───────────────────────────────────────────────────

    def _build_args(self, backup_only: bool = False) -> object:
        """Build a args namespace matching openwrt_installer.py expectations."""
        import types
        args = types.SimpleNamespace(
            model     = self.MODEL_OPTIONS.get(self._model_var.get(), "auto"),
            ip        = self._ip_var.get().strip(),
            password  = self._password_var.get().strip(),
            backup_only = backup_only or self._backup_only_var.get(),
            no_backup = self._no_backup_var.get(),
            force     = self._force_var.get(),
            verbose   = self._verbose_var.get(),
            recovery  = False,
            openwrt_ip = self._openwrt_ip_var.get().strip(),
            fw_dir    = "firmware",
            backup_dir = "backups",
        )
        return args

    def _set_running(self, running: bool) -> None:
        """Enable/disable controls while installation is in progress."""
        state = tk.DISABLED if running else tk.NORMAL
        self._start_btn.configure(state=state)
        self._backup_btn.configure(state=state)
        self._stop_btn.configure(state=tk.NORMAL if running else tk.DISABLED)

    def _run_install_thread(self, args) -> None:
        """Worker function executed in a background thread."""
        import yaml
        from pathlib import Path as P
        from openwrt_installer import run_install
        from utils.logger import get_logger as _gl

        config_path = P(__file__).parent.parent / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)

        log = _gl("gui_thread")
        try:
            # Update progress via tkinter-safe after() calls
            self.after(0, lambda: self._progress.set_step(0, "Starting…"))
            exit_code = run_install(args, cfg, log,
                                    progress_callback=self._progress_callback)
            if exit_code == 0:
                self.after(0, lambda: self._progress.set_step(8, "Done!"))
                self.after(0, lambda: self._log("SUCCESS", "🎉 Installation complete!"))
            else:
                self.after(0, lambda: self._progress.set_error(f"Exit code {exit_code}"))
                self.after(0, lambda: self._log("ERROR", f"Installer exited with code {exit_code}"))
        except Exception as exc:
            self.after(0, lambda: self._progress.set_error(str(exc)))
            self.after(0, lambda: self._log("ERROR", f"Unexpected error: {exc}"))
        finally:
            self.after(0, lambda: self._set_running(False))

    def _progress_callback(self, step: int, sub_text: str = "") -> None:
        """Called from installer thread to update GUI progress."""
        self.after(0, lambda: self._progress.set_step(step, sub_text))

    def _on_start(self) -> None:
        if self._install_thread and self._install_thread.is_alive():
            return
        self._stop_event.clear()
        self._log_viewer.clear()
        self._set_running(True)
        self._progress.set_step(0, "Preparing…")
        self._log("STEP", "=== Starting OpenWRT Installation ===")
        args = self._build_args(backup_only=False)
        self._install_thread = threading.Thread(
            target=self._run_install_thread, args=(args,), daemon=True
        )
        self._install_thread.start()

    def _on_backup_only(self) -> None:
        if self._install_thread and self._install_thread.is_alive():
            return
        self._stop_event.clear()
        self._log_viewer.clear()
        self._set_running(True)
        self._log("STEP", "=== Backup-Only Mode ===")
        args = self._build_args(backup_only=True)
        self._install_thread = threading.Thread(
            target=self._run_install_thread, args=(args,), daemon=True
        )
        self._install_thread.start()

    def _on_stop(self) -> None:
        self._stop_event.set()
        self._log("WARNING", "Stop requested – please wait for safe abort…")

    def _on_recovery(self) -> None:
        """Open a small recovery dialog."""
        from modules.recovery import RecoveryManager
        model_key = self.MODEL_OPTIONS.get(self._model_var.get(), "4a_gigabit_v1")
        rec = RecoveryManager(model_key=model_key)

        win = tk.Toplevel(self)
        win.title("Recovery Tools")
        win.configure(bg=T.BG)
        win.geometry("520x380")
        win.resizable(False, False)

        tk.Label(win, text="🛠  Recovery & Unbrick Tools",
                 bg=T.BG, fg=T.ACCENT,
                 font=(T.FONT_FAMILY, 13, "bold")).pack(pady=(16, 8))

        info = tk.Text(win, bg=T.BG2, fg=T.TEXT,
                       font=(T.FONT_MONO, T.FONT_SMALL),
                       width=62, height=14, relief="flat", padx=8, pady=8)
        info.pack(padx=12, pady=4)
        instructions = (
            "MiWifi Repair Tool:\n"
            "  Download from: https://www.miwifi.com/miwifi_download.html\n\n"
            "TFTP Recovery (4A Gigabit):\n"
            "  1. Set PC IP: 192.168.31.100 / 255.255.255.0\n"
            "  2. Start TFTP server (Tftpd64)\n"
            "  3. Place stock firmware as 'root_fs' in TFTP root\n"
            "  4. Hold Reset → Power ON → release when LED blinks\n\n"
            "Reset Button Recovery (4C):\n"
            "  1. Hold RESET while powering on (~10s)\n"
            "  2. Connect to http://192.168.31.1 to upload firmware\n\n"
            "OpenWRT Wiki:\n"
            "  4A: https://openwrt.org/toh/xiaomi/mi_router_4a_gigabit\n"
            "  4C: https://openwrt.org/toh/xiaomi/mi_router_4c"
        )
        info.insert(tk.END, instructions)
        info.configure(state=tk.DISABLED)

        btn_row = tk.Frame(win, bg=T.BG)
        btn_row.pack(pady=8)
        ttk.Button(btn_row, text="Launch MiWifi Repair Tool",
                   command=lambda: rec.try_miwifi_tool(),
                   style="Accent.TButton").pack(side=tk.LEFT, padx=8)
        ttk.Button(btn_row, text="Close",
                   command=win.destroy).pack(side=tk.LEFT)
