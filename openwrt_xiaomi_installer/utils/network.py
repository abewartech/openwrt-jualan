"""
utils/network.py
================
Low-level network helpers: ping, port-alive checks, HTTP probing.
All functions are synchronous and OS-agnostic (Windows + Linux).
"""

import socket
import subprocess
import sys
import time
from typing import Optional

import requests

from utils.logger import get_logger

log = get_logger("network")

# ─────────────────────────────────────────────────────────────────────────────

def ping(host: str, count: int = 1, timeout: int = 2) -> bool:
    """
    Send ICMP echo request.  Returns True if host is alive.
    Uses platform-appropriate flags (-n for Windows, -c for Linux/macOS).
    """
    param = "-n" if sys.platform.startswith("win") else "-c"
    timeout_flag = "-w" if sys.platform.startswith("win") else "-W"
    cmd = ["ping", param, str(count), timeout_flag, str(timeout), host]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def wait_for_ping(
    host: str,
    max_attempts: int = 30,
    interval: int = 5,
    timeout: int = 2,
) -> bool:
    """
    Poll *host* with ICMP ping until it responds or *max_attempts* exceeded.
    Returns True when the host is reachable.
    """
    log.info("Waiting for %s to become reachable (max %ds)…", host, max_attempts * interval)
    for attempt in range(1, max_attempts + 1):
        if ping(host, count=1, timeout=timeout):
            log.info("Host %s is alive (attempt %d/%d)", host, attempt, max_attempts)
            return True
        log.debug("Ping attempt %d/%d failed, retrying in %ds…", attempt, max_attempts, interval)
        time.sleep(interval)
    log.error("Host %s did not respond after %d attempts.", host, max_attempts)
    return False


def is_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """Return True if a TCP connection to *host:port* can be established."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def wait_for_port(
    host: str,
    port: int,
    max_attempts: int = 20,
    interval: int = 5,
    timeout: float = 3.0,
) -> bool:
    """Poll TCP port until open or max_attempts exceeded."""
    log.info("Waiting for %s:%d to open…", host, port)
    for attempt in range(1, max_attempts + 1):
        if is_port_open(host, port, timeout):
            log.info("Port %s:%d is open (attempt %d)", host, port, attempt)
            return True
        log.debug("Port attempt %d/%d…", attempt, max_attempts)
        time.sleep(interval)
    log.error("Port %s:%d did not open in time.", host, port)
    return False


def http_get(
    url: str,
    timeout: int = 10,
    session: Optional[requests.Session] = None,
    **kwargs,
) -> Optional[requests.Response]:
    """Perform a GET request, returning Response or None on error."""
    client = session or requests
    try:
        resp = client.get(url, timeout=timeout, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        log.debug("GET %s failed: %s", url, exc)
        return None


def http_post(
    url: str,
    data=None,
    json_data=None,
    timeout: int = 10,
    session: Optional[requests.Session] = None,
    **kwargs,
) -> Optional[requests.Response]:
    """Perform a POST request, returning Response or None on error."""
    client = session or requests
    try:
        resp = client.post(
            url,
            data=data,
            json=json_data,
            timeout=timeout,
            **kwargs,
        )
        return resp
    except requests.RequestException as exc:
        log.debug("POST %s failed: %s", url, exc)
        return None


def get_local_ip() -> str:
    """Return the local IP that would be used to reach 192.168.31.1."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.31.1", 80))
            return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"
