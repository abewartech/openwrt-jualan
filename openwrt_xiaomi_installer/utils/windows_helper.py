"""
utils/windows_helper.py
=======================
Windows-specific helpers:
  • Check for WSL availability
  • Run commands in WSL (needed for pexpect-based interactive sessions)
  • Locate MiWifi Repair Tool (Xiaomi Recovery Tool)
  • Warn when running without admin privileges
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

log = get_logger("windows_helper")


# ─────────────────────────────────────────────────────────────────────────────
# Platform guard
# ─────────────────────────────────────────────────────────────────────────────

IS_WINDOWS = sys.platform.startswith("win")


def assert_windows() -> None:
    if not IS_WINDOWS:
        raise EnvironmentError("This helper is only meaningful on Windows.")


# ─────────────────────────────────────────────────────────────────────────────
# Admin privilege check
# ─────────────────────────────────────────────────────────────────────────────

def is_admin() -> bool:
    """Return True when the process has administrator / root privileges."""
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        return os.geteuid() == 0


def warn_if_not_admin() -> None:
    if not is_admin():
        log.warning(
            "⚠  Running WITHOUT administrator privileges. "
            "Some network operations (raw ping, arp) may fail on Windows."
        )


# ─────────────────────────────────────────────────────────────────────────────
# WSL helpers
# ─────────────────────────────────────────────────────────────────────────────

def wsl_available() -> bool:
    """Return True if WSL (Windows Subsystem for Linux) is installed."""
    if not IS_WINDOWS:
        return False
    return shutil.which("wsl") is not None


def run_in_wsl(command: str, timeout: int = 60) -> tuple[int, str, str]:
    """
    Execute *command* inside WSL bash and return (returncode, stdout, stderr).
    Raises RuntimeError if WSL is not available.
    """
    if not wsl_available():
        raise RuntimeError(
            "WSL is not available on this system.  "
            "Install WSL: https://docs.microsoft.com/en-us/windows/wsl/install"
        )
    result = subprocess.run(
        ["wsl", "bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def check_wsl_python() -> bool:
    """Verify that Python3 is installed inside WSL."""
    try:
        rc, out, _ = run_in_wsl("python3 --version")
        if rc == 0:
            log.debug("WSL Python: %s", out.strip())
            return True
    except RuntimeError:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
# MiWifi Repair Tool (Xiaomi Recovery Tool) detection
# ─────────────────────────────────────────────────────────────────────────────

MIWIFI_TOOL_NAMES = [
    "MiWiFiRepairTool.x86.exe",
    "MiWiFiRepairTool.exe",
    "MiWiFi_Repair.exe",
]

MIWIFI_COMMON_PATHS = [
    Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "MiWiFi",
    Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "MiWiFi",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
]


def find_miwifi_tool() -> Optional[Path]:
    """Search common locations for the MiWifi Repair Tool executable."""
    # Check PATH first
    for name in MIWIFI_TOOL_NAMES:
        found = shutil.which(name)
        if found:
            return Path(found)
    # Check common directories
    for directory in MIWIFI_COMMON_PATHS:
        if directory.exists():
            for name in MIWIFI_TOOL_NAMES:
                candidate = directory / name
                if candidate.exists():
                    log.debug("Found MiWifi Repair Tool at: %s", candidate)
                    return candidate
    return None


def launch_miwifi_tool(tool_path: Optional[Path] = None) -> bool:
    """
    Attempt to launch the MiWifi Repair Tool.
    Returns True if launched successfully.
    """
    if not IS_WINDOWS:
        log.warning("MiWifi Repair Tool is a Windows-only application.")
        return False
    path = tool_path or find_miwifi_tool()
    if path is None:
        log.error(
            "MiWifi Repair Tool not found.  "
            "Download from: https://www.miwifi.com/miwifi_download.html"
        )
        return False
    try:
        subprocess.Popen([str(path)], shell=False)
        log.info("Launched MiWifi Repair Tool: %s", path)
        return True
    except OSError as exc:
        log.error("Failed to launch MiWifi Repair Tool: %s", exc)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Colour output toggle (colorama init)
# ─────────────────────────────────────────────────────────────────────────────

def enable_ansi_colors() -> None:
    """Enable ANSI escape sequences on Windows terminal (colorama + VTP)."""
    if IS_WINDOWS:
        try:
            from colorama import init as colorama_init
            colorama_init(autoreset=True)
            log.debug("Colorama ANSI enabled.")
        except ImportError:
            # Try to enable Windows ANSI via ctypes
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                log.debug("Windows VTP mode enabled.")
            except Exception:
                pass
