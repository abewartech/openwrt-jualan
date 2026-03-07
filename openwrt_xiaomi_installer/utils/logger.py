"""
utils/logger.py
===============
Centralized logging setup for OpenWRT Xiaomi Installer.
Creates both a file handler (rotating) and a coloured console handler.
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Colour map for log levels (console only)
# ─────────────────────────────────────────────────────────────────────────────
LEVEL_COLORS = {
    "DEBUG":    Fore.CYAN    if COLORAMA_AVAILABLE else "",
    "INFO":     Fore.GREEN   if COLORAMA_AVAILABLE else "",
    "WARNING":  Fore.YELLOW  if COLORAMA_AVAILABLE else "",
    "ERROR":    Fore.RED     if COLORAMA_AVAILABLE else "",
    "CRITICAL": Fore.MAGENTA if COLORAMA_AVAILABLE else "",
}
RESET = Style.RESET_ALL if COLORAMA_AVAILABLE else ""


class ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI colour codes to console output."""

    def format(self, record: logging.LogRecord) -> str:
        color = LEVEL_COLORS.get(record.levelname, "")
        message = super().format(record)
        if COLORAMA_AVAILABLE:
            return f"{color}{message}{RESET}"
        return message


def setup_logger(
    name: str = "openwrt_installer",
    log_dir: str | Path = ".",
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,   # 10 MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    Create and configure the root application logger.

    Parameters
    ----------
    name          : Logger name (module hierarchy root).
    log_dir       : Directory where log files are written.
    console_level : Minimum level shown on stdout.
    file_level    : Minimum level written to file.
    max_bytes     : Maximum size of each log file before rotation.
    backup_count  : Number of rotated log files to keep.

    Returns
    -------
    logging.Logger configured with both handlers.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"openwrt_installer_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)          # handlers filter individually

    # ── File handler ────────────────────────────────────────────────────────
    file_fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    fh.setLevel(file_level)
    fh.setFormatter(file_fmt)
    logger.addHandler(fh)

    # ── Console handler ──────────────────────────────────────────────────────
    console_fmt = ColoredFormatter(
        fmt="%(asctime)s [%(levelname)-8s] %(message)s",
        datefmt="%H:%M:%S",
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(console_level)
    ch.setFormatter(console_fmt)
    logger.addHandler(ch)

    logger.info("Logging initialised → %s", log_file)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the application root."""
    return logging.getLogger(f"openwrt_installer.{name}")
