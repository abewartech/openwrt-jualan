"""
utils/interactive_session.py
============================
Windows-compatible replacement for pexpect.

On Windows, pexpect cannot spawn PTY-based processes.
This module provides three backends, selected automatically:

  1. **SubprocessSession** (Windows native)
     - Uses subprocess with pipes + threading for non-blocking I/O
     - Works for telnet, netcat, and similar line-oriented protocols
     - No external dependencies

  2. **WslSession** (WSL fallback)
     - Wraps `wsl bash -c ...` when WSL is available
     - Full pexpect inside WSL

  3. **TelnetSession** (stdlib telnetlib)
     - Direct use of Python's telnetlib for telnet specifically
     - Most reliable for the telnet login/command use-case

Usage
-----
    from utils.interactive_session import open_session

    with open_session("telnet", host="192.168.31.1", port=23) as s:
        s.expect("login:")
        s.send("root")
        s.expect("Password:")
        s.send("root")
        s.expect(["#", "$"])
        output = s.run_command("cat /proc/mtd")
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import telnetlib
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional, Union

from utils.logger import get_logger

log = get_logger("interactive_session")

IS_WINDOWS = sys.platform.startswith("win")


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────

class BaseSession(ABC):
    """Abstract interactive session interface."""

    @abstractmethod
    def send(self, text: str, newline: bool = True) -> None:
        """Send text (optionally followed by newline)."""

    @abstractmethod
    def expect(
        self,
        patterns: Union[str, list[str]],
        timeout: float = 15.0,
    ) -> int:
        """
        Wait for one of *patterns* to appear in output.
        Returns the index of the matched pattern.
        Raises TimeoutError if none match within *timeout* seconds.
        """

    @abstractmethod
    def read_until(self, pattern: str, timeout: float = 15.0) -> str:
        """Read until *pattern* is found or timeout, returning all output."""

    @abstractmethod
    def close(self) -> None:
        """Close the session."""

    def run_command(self, command: str, timeout: float = 30.0, prompt: str = r"[#\$] ?$") -> str:
        """
        Send *command*, wait for shell prompt, return command output.
        """
        marker = f"__DONE_{int(time.time())}__"
        self.send(f"{command}; echo {marker}")
        output = self.read_until(marker, timeout=timeout)
        # Strip marker and echoed command
        lines = output.splitlines()
        result = []
        past_echo = False
        for line in lines:
            if not past_echo and command[:30] in line:
                past_echo = True
                continue
            if marker in line:
                break
            if past_echo:
                result.append(line)
        return "\n".join(result)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Backend 1: stdlib telnetlib (best for telnet use-case)
# ─────────────────────────────────────────────────────────────────────────────

class TelnetSession(BaseSession):
    """
    Session over telnetlib.Telnet.
    Most reliable backend for Xiaomi router telnet access.
    Works on Windows and Linux without extra dependencies.
    """

    def __init__(self, host: str, port: int = 23, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._tn: Optional[telnetlib.Telnet] = None
        self._buf: list[str] = []
        self._connect()

    def _connect(self) -> None:
        log.info("TelnetSession: connecting to %s:%d", self.host, self.port)
        self._tn = telnetlib.Telnet(self.host, self.port, timeout=self.timeout)
        log.info("TelnetSession: connected.")

    def send(self, text: str, newline: bool = True) -> None:
        payload = (text + ("\n" if newline else "")).encode("utf-8", errors="replace")
        self._tn.write(payload)

    def expect(
        self,
        patterns: Union[str, list[str]],
        timeout: float = 15.0,
    ) -> int:
        if isinstance(patterns, str):
            patterns = [patterns]
        compiled = [re.compile(p.encode()) for p in patterns]
        idx, m, data = self._tn.expect(compiled, timeout=timeout)
        if idx == -1:
            raise TimeoutError(
                f"Timeout waiting for {patterns} on {self.host}:{self.port}"
            )
        return idx

    def read_until(self, pattern: str, timeout: float = 15.0) -> str:
        raw = self._tn.read_until(pattern.encode(), timeout=timeout)
        return raw.decode(errors="replace")

    def close(self) -> None:
        if self._tn:
            try:
                self._tn.close()
            except Exception:
                pass
            self._tn = None
            log.debug("TelnetSession: closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Backend 2: subprocess + pipe reader thread (Windows native)
# ─────────────────────────────────────────────────────────────────────────────

class SubprocessSession(BaseSession):
    """
    Spawn an interactive process (e.g. system telnet.exe) via subprocess.
    Non-blocking reads via a background reader thread + Queue.

    Works entirely without PTY — suitable for Windows.
    Note: ANSI sequences are NOT interpreted; raw text only.
    """

    def __init__(self, command: list[str], timeout: float = 10.0):
        self.timeout = timeout
        self._buf = queue.Queue()
        self._lock = threading.Lock()

        log.info("SubprocessSession: spawning %s", command)
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        # Background thread drains stdout into queue
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        try:
            while True:
                byte = self._proc.stdout.read(1)
                if not byte:
                    break
                self._buf.put(byte.decode(errors="replace"))
        except Exception:
            pass

    def _drain(self, timeout: float) -> str:
        """Collect available output from the queue."""
        collected = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                collected.append(self._buf.get(timeout=0.05))
            except queue.Empty:
                if collected:
                    # A short quiet period after data → probably done
                    try:
                        # Grab anything else that arrives quickly
                        while True:
                            collected.append(self._buf.get(timeout=0.02))
                    except queue.Empty:
                        break
        return "".join(collected)

    def send(self, text: str, newline: bool = True) -> None:
        payload = (text + ("\n" if newline else "")).encode("utf-8", errors="replace")
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def expect(
        self,
        patterns: Union[str, list[str]],
        timeout: float = 15.0,
    ) -> int:
        if isinstance(patterns, str):
            patterns = [patterns]
        compiled = [re.compile(p) for p in patterns]
        accumulated = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                ch = self._buf.get(timeout=0.1)
                accumulated += ch
                for i, pat in enumerate(compiled):
                    if pat.search(accumulated):
                        return i
            except queue.Empty:
                pass
        raise TimeoutError(
            f"Timeout ({timeout}s) waiting for {patterns}"
        )

    def read_until(self, pattern: str, timeout: float = 15.0) -> str:
        accumulated = ""
        compiled = re.compile(re.escape(pattern))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                ch = self._buf.get(timeout=0.1)
                accumulated += ch
                if compiled.search(accumulated):
                    return accumulated
            except queue.Empty:
                pass
        return accumulated  # return what we have on timeout

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
        except Exception:
            pass
        log.debug("SubprocessSession: closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Backend 3: WSL pexpect session
# ─────────────────────────────────────────────────────────────────────────────

class WslSession(BaseSession):
    """
    Run an interactive command inside WSL and wrap it with pexpect.
    Only available when WSL is installed AND pexpect is importable in WSL Python.
    """

    def __init__(self, wsl_command: str, timeout: float = 10.0):
        try:
            import pexpect
        except ImportError:
            raise ImportError(
                "pexpect is not installed in WSL Python. "
                "Install with: sudo apt install python3-pexpect"
            )
        self.timeout = timeout
        log.info("WslSession: starting via WSL: %s", wsl_command)
        import pexpect
        self._child = pexpect.spawnu(
            "wsl",
            ["bash", "-c", wsl_command],
            timeout=timeout,
            encoding="utf-8",
        )

    def send(self, text: str, newline: bool = True) -> None:
        if newline:
            self._child.sendline(text)
        else:
            self._child.send(text)

    def expect(
        self,
        patterns: Union[str, list[str]],
        timeout: float = 15.0,
    ) -> int:
        if isinstance(patterns, str):
            patterns = [patterns]
        return self._child.expect(patterns, timeout=timeout)

    def read_until(self, pattern: str, timeout: float = 15.0) -> str:
        self._child.expect(re.escape(pattern), timeout=timeout)
        return self._child.before + pattern

    def close(self) -> None:
        try:
            self._child.close()
        except Exception:
            pass
        log.debug("WslSession: closed.")


# ─────────────────────────────────────────────────────────────────────────────
# Factory: open_session
# ─────────────────────────────────────────────────────────────────────────────

def open_session(
    session_type: str = "telnet",
    *,
    host: str = "192.168.31.1",
    port: int = 23,
    command: Optional[list[str]] = None,
    wsl_command: Optional[str] = None,
    prefer_wsl: bool = False,
    timeout: float = 10.0,
) -> BaseSession:
    """
    Factory function returning the best available session backend.

    Parameters
    ----------
    session_type : "telnet" | "subprocess" | "wsl" | "auto"
    host         : Target host for telnet backend
    port         : Target port for telnet backend
    command      : Command list for subprocess backend
    wsl_command  : Shell command string for WSL backend
    prefer_wsl   : If True, prefer WSL over subprocess when both available
    timeout      : Connection / read timeout in seconds

    Returns
    -------
    A BaseSession implementation.
    """
    from utils.windows_helper import wsl_available

    if session_type == "telnet" or session_type == "auto":
        return TelnetSession(host=host, port=port, timeout=timeout)

    if session_type == "wsl":
        if not wsl_available():
            raise RuntimeError("WSL is not available on this system.")
        cmd = wsl_command or f"telnet {host} {port}"
        return WslSession(wsl_command=cmd, timeout=timeout)

    if session_type == "subprocess":
        if command is None:
            # Default to Windows built-in telnet (if enabled)
            command = ["telnet", host, str(port)]
        return SubprocessSession(command=command, timeout=timeout)

    raise ValueError(f"Unknown session_type: {session_type!r}")


def open_telnet(
    host: str,
    port: int = 23,
    timeout: float = 10.0,
    prefer_wsl: bool = False,
) -> BaseSession:
    """Convenience: open the best telnet session available on this OS."""
    from utils.windows_helper import wsl_available
    if prefer_wsl and wsl_available():
        log.info("Using WSL backend for telnet.")
        return WslSession(
            wsl_command=f"telnet {host} {port}",
            timeout=timeout,
        )
    # TelnetSession (stdlib) is always preferred for Xiaomi routers
    return TelnetSession(host=host, port=port, timeout=timeout)
