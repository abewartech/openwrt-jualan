#!/usr/bin/env python3
"""
openwrt_gui.py
==============
Graphical (tkinter) launcher for the OpenWRT Xiaomi Installer.

Usage:
    python openwrt_gui.py
    # or via windows_runner.bat --gui
    # or via PowerShell: install_setup.ps1 -GUI

Requires: tkinter (included with standard CPython on Windows)
"""

import sys
import os

# Ensure the installer root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _check_tkinter() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(
            "ERROR: tkinter is not available.\n"
            "On Windows, reinstall Python and ensure 'tcl/tk and IDLE' is checked.\n"
            "On Linux: sudo apt install python3-tk",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    _check_tkinter()

    # Setup logging BEFORE importing the app (so QueueLogHandler can attach)
    from utils.logger import setup_logger
    import logging
    setup_logger(console_level=logging.DEBUG)

    # Windows colour support
    from utils.windows_helper import enable_ansi_colors
    enable_ansi_colors()

    from gui.app import InstallerApp
    app = InstallerApp()

    # Center the window on screen
    app.update_idletasks()
    w, h = app.winfo_reqwidth(), app.winfo_reqheight()
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    app.geometry(f"{max(w, 860)}x{max(h, 680)}+{x}+{y}")

    app.mainloop()


if __name__ == "__main__":
    main()
