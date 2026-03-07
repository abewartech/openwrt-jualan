"""
modules/telnet_client.py
========================
Thin telnet wrapper (Python stdlib telnetlib) used by backup.py and flasher.py.
Handles login prompt + interactive command execution on Xiaomi stock firmware.
"""

import re
import telnetlib
import time
from typing import Optional

from utils.logger import get_logger

log = get_logger("telnet_client")

# Read timeout for general commands
DEFAULT_TIMEOUT = 30
# Larger timeout for write-intensive operations (dd, mtd write)
LONG_TIMEOUT = 300


class TelnetClient:
    """
    Authenticated telnet session to the Xiaomi router.

    Parameters
    ----------
    host     : Router IP
    port     : Telnet port (default 23)
    username : Login username (default 'root')
    password : Login password (default 'root')
    timeout  : Connection timeout in seconds
    """

    PROMPT = re.compile(rb"[#\$] ?$")
    LOGIN_PROMPT = re.compile(rb"[Ll]ogin:|[Uu]sername:")
    PASS_PROMPT  = re.compile(rb"[Pp]assword:")

    def __init__(
        self,
        host: str,
        port: int = 23,
        username: str = "root",
        password: str = "root",
        timeout: int = 10,
    ):
        self.host     = host
        self.port     = port
        self.username = username
        self.password = password
        self.timeout  = timeout
        self._tn: Optional[telnetlib.Telnet] = None

    def connect(self) -> None:
        """Open telnet connection and authenticate."""
        log.info("Connecting to telnet %s:%d…", self.host, self.port)
        self._tn = telnetlib.Telnet(self.host, self.port, timeout=self.timeout)

        # Handle login prompt
        idx, _, _ = self._tn.expect(
            [self.LOGIN_PROMPT, self.PROMPT], timeout=15
        )
        if idx == 0:
            self._tn.write(self.username.encode() + b"\n")
            self._tn.expect([self.PASS_PROMPT], timeout=10)
            self._tn.write(self.password.encode() + b"\n")
            self._tn.expect([self.PROMPT], timeout=10)

        log.info("✔  Telnet session established.")

    def disconnect(self) -> None:
        """Close the telnet connection."""
        if self._tn:
            try:
                self._tn.close()
            except Exception:
                pass
            self._tn = None
            log.debug("Telnet connection closed.")

    def run_command(
        self,
        command: str,
        timeout: int = DEFAULT_TIMEOUT,
        expect_marker: Optional[str] = None,
    ) -> str:
        """
        Execute *command* and return its stdout output as a string.

        Parameters
        ----------
        command       : Shell command to run
        timeout       : Max seconds to wait for completion
        expect_marker : Optional unique string to wait for (used for long ops)
        """
        if not self._tn:
            raise RuntimeError("Not connected.  Call connect() first.")

        marker = expect_marker or f"__CMD_DONE_{int(time.time())}__"
        full_cmd = f"{command}; echo {marker}\n"
        self._tn.write(full_cmd.encode())

        output = self._tn.read_until(marker.encode(), timeout=timeout)
        text = output.decode(errors="replace")

        # Strip the echo of the command itself and the marker
        lines = text.splitlines()
        # Remove first line (echoed command) and last line (marker)
        inner = []
        skip_first = True
        for line in lines:
            if skip_first and command[:20] in line:
                skip_first = False
                continue
            if marker in line:
                break
            inner.append(line)
        return "\n".join(inner)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()
