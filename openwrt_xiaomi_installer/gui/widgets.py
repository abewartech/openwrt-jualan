"""
gui/widgets.py
==============
Reusable tkinter widget helpers for the OpenWRT installer GUI.

Provides:
  • DarkTheme  – colour palette and font constants
  • StyledButton, StyledLabel, StyledEntry, StyledCombobox
  • LogViewer  – scrollable text widget with coloured log levels
  • ProgressSection – label + ttk.Progressbar combo
  • SectionFrame – labelled LabelFrame with consistent styling
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Dark theme palette
# ─────────────────────────────────────────────────────────────────────────────

class DarkTheme:
    BG           = "#1e1e2e"   # main background (Catppuccin Mocha base)
    BG2          = "#181825"   # slightly darker panel
    BG3          = "#313244"   # card / frame background
    SURFACE      = "#45475a"   # input / entry background
    ACCENT       = "#cba6f7"   # purple accent (Mauve)
    ACCENT2      = "#89b4fa"   # blue accent (Blue)
    SUCCESS      = "#a6e3a1"   # green (Green)
    WARNING      = "#f9e2af"   # yellow (Yellow)
    ERROR        = "#f38ba8"   # red (Red)
    TEXT         = "#cdd6f4"   # primary text
    TEXT_MUTED   = "#6c7086"   # secondary / placeholder text
    BORDER       = "#3d3d5c"   # border/separator

    FONT_FAMILY  = "Segoe UI"
    FONT_SIZE    = 10
    FONT_SMALL   = 9
    FONT_LARGE   = 12
    FONT_MONO    = "Consolas"

    @classmethod
    def configure_ttk(cls, style: ttk.Style) -> None:
        """Apply dark theme to ttk widgets."""
        style.theme_use("clam")

        style.configure(".",
            background=cls.BG,
            foreground=cls.TEXT,
            fieldbackground=cls.SURFACE,
            troughcolor=cls.BG2,
            selectbackground=cls.ACCENT,
            selectforeground=cls.BG,
            font=(cls.FONT_FAMILY, cls.FONT_SIZE),
        )
        style.configure("TFrame",        background=cls.BG)
        style.configure("TLabel",        background=cls.BG, foreground=cls.TEXT)
        style.configure("TLabelframe",   background=cls.BG3, foreground=cls.ACCENT)
        style.configure("TLabelframe.Label", background=cls.BG3, foreground=cls.ACCENT,
                         font=(cls.FONT_FAMILY, cls.FONT_SIZE, "bold"))
        style.configure("TEntry",        fieldbackground=cls.SURFACE, foreground=cls.TEXT,
                         insertcolor=cls.TEXT)
        style.configure("TCombobox",     fieldbackground=cls.SURFACE, foreground=cls.TEXT,
                         selectbackground=cls.ACCENT, arrowcolor=cls.ACCENT)
        style.configure("TScrollbar",    background=cls.BG3, troughcolor=cls.BG2,
                         arrowcolor=cls.TEXT_MUTED)

        # Progressbar
        style.configure("TProgressbar",
            troughcolor=cls.BG2,
            background=cls.ACCENT2,
            bordercolor=cls.BORDER,
            lightcolor=cls.ACCENT2,
            darkcolor=cls.ACCENT2,
        )
        style.configure("Success.TProgressbar", background=cls.SUCCESS)
        style.configure("Error.TProgressbar",   background=cls.ERROR)

        # Buttons
        style.configure("TButton",
            background=cls.BG3, foreground=cls.TEXT,
            bordercolor=cls.BORDER, relief="flat", padding=(12, 6),
            font=(cls.FONT_FAMILY, cls.FONT_SIZE),
        )
        style.map("TButton",
            background=[("active", cls.SURFACE), ("pressed", cls.BG2)],
        )
        style.configure("Accent.TButton",
            background=cls.ACCENT, foreground=cls.BG,
            bordercolor=cls.ACCENT, font=(cls.FONT_FAMILY, cls.FONT_SIZE, "bold"),
        )
        style.map("Accent.TButton",
            background=[("active", cls.ACCENT2), ("pressed", cls.BORDER)],
        )
        style.configure("Danger.TButton",
            background=cls.ERROR, foreground=cls.BG,
            font=(cls.FONT_FAMILY, cls.FONT_SIZE, "bold"),
        )
        style.map("Danger.TButton",
            background=[("active", "#eb8fa8"), ("pressed", cls.BORDER)],
        )

T = DarkTheme   # shorthand


# ─────────────────────────────────────────────────────────────────────────────
# SectionFrame
# ─────────────────────────────────────────────────────────────────────────────

class SectionFrame(ttk.LabelFrame):
    """LabelFrame with consistent dark styling."""

    def __init__(self, parent, title: str, **kwargs):
        super().__init__(parent, text=f"  {title}  ", padding=(10, 6), **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# LogViewer
# ─────────────────────────────────────────────────────────────────────────────

class LogViewer(tk.Frame):
    """
    Scrollable Text widget that displays coloured log messages.

    Log levels are highlighted:
      DEBUG   → muted grey
      INFO    → normal text
      WARNING → yellow
      ERROR   → red
      CRITICAL→ bright red
      SUCCESS → green (custom level for the GUI)
    """

    TAG_COLORS = {
        "DEBUG":    T.TEXT_MUTED,
        "INFO":     T.TEXT,
        "WARNING":  T.WARNING,
        "ERROR":    T.ERROR,
        "CRITICAL": T.ERROR,
        "SUCCESS":  T.SUCCESS,
        "STEP":     T.ACCENT2,
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=T.BG2, **kwargs)

        self._text = tk.Text(
            self,
            bg=T.BG2,
            fg=T.TEXT,
            font=(T.FONT_MONO, T.FONT_SMALL),
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief="flat",
            border=0,
            selectbackground=T.SURFACE,
            insertbackground=T.TEXT,
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure colour tags
        for tag, color in self.TAG_COLORS.items():
            self._text.tag_configure(tag, foreground=color)

    def append(self, message: str, level: str = "INFO") -> None:
        """Append a log message with appropriate colour tag."""
        self._text.configure(state=tk.NORMAL)
        tag = level.upper() if level.upper() in self.TAG_COLORS else "INFO"
        self._text.insert(tk.END, message + "\n", tag)
        self._text.see(tk.END)    # auto-scroll to bottom
        self._text.configure(state=tk.DISABLED)

    def clear(self) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.configure(state=tk.DISABLED)


# ─────────────────────────────────────────────────────────────────────────────
# ProgressSection
# ─────────────────────────────────────────────────────────────────────────────

class ProgressSection(tk.Frame):
    """
    A step label + overall progress bar + current sub-task label.
    """

    STEPS = [
        "Idle",
        "1. Detecting Router",
        "2. Running Exploit",
        "3. Telnet Connection",
        "4. Backing Up Partitions",
        "5. Downloading Firmware",
        "6. Flashing OpenWRT",
        "7. Verifying Installation",
        "Complete",
    ]

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=T.BG, **kwargs)

        # Step label
        self._step_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self._step_var,
                  font=(T.FONT_FAMILY, T.FONT_SMALL),
                  foreground=T.TEXT_MUTED).pack(anchor="w", pady=(0, 4))

        # Progress bar
        self._bar = ttk.Progressbar(
            self, orient="horizontal", mode="determinate",
            maximum=len(self.STEPS) - 1, style="TProgressbar",
        )
        self._bar.pack(fill=tk.X)

        # Sub-task label
        self._sub_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._sub_var,
                  font=(T.FONT_FAMILY, T.FONT_SMALL),
                  foreground=T.TEXT_MUTED).pack(anchor="w", pady=(4, 0))

    def set_step(self, step_index: int, sub_text: str = "") -> None:
        """Set the current progress step (0 = idle, len-1 = complete)."""
        step_index = max(0, min(step_index, len(self.STEPS) - 1))
        self._step_var.set(self.STEPS[step_index])
        self._bar["value"] = step_index
        self._sub_var.set(sub_text)

        # Colour: green on complete, red on error
        if step_index == len(self.STEPS) - 1:
            self._bar.configure(style="Success.TProgressbar")
        else:
            self._bar.configure(style="TProgressbar")

    def set_error(self, message: str = "Error") -> None:
        self._step_var.set(f"✘ {message}")
        self._sub_var.set("See log for details")
        self._bar.configure(style="Error.TProgressbar")

    def pulse(self) -> None:
        """Switch to indeterminate mode for operations with unknown duration."""
        self._bar.configure(mode="indeterminate")
        self._bar.start(12)

    def stop_pulse(self) -> None:
        self._bar.stop()
        self._bar.configure(mode="determinate")
