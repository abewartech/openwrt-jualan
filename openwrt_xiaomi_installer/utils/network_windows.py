"""
utils/network_windows.py
========================
Windows-specific network adapter detection and management.

Features:
  • Enumerate all active IPv4 network adapters via subprocess (ipconfig) and
    optionally via WMI (pywin32) for richer metadata.
  • Find the adapter most likely connected to the Xiaomi router (192.168.31.x)
  • Suggest / set a static IP on that adapter if not already configured
  • Detect multiple NICs and help the user choose the right one
  • Integration helpers for MiWifi Repair Tool
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

from utils.logger import get_logger

log = get_logger("network_windows")

IS_WINDOWS = sys.platform.startswith("win")

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class NetworkAdapter:
    name: str
    description: str = ""
    mac: str = ""
    ip_addresses: list[str] = field(default_factory=list)
    subnet_masks: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)
    is_connected: bool = True
    interface_index: int = -1

    def has_ip_in_subnet(self, prefix: str) -> bool:
        return any(ip.startswith(prefix) for ip in self.ip_addresses)

    def __str__(self) -> str:
        ips = ", ".join(self.ip_addresses) or "no IP"
        return f"{self.name} ({ips})"


# ─────────────────────────────────────────────────────────────────────────────
# ipconfig parser (no dependencies)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ipconfig() -> list[NetworkAdapter]:
    """
    Parse `ipconfig /all` output into a list of NetworkAdapter objects.
    Works without pywin32 / WMI.
    """
    try:
        result = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True, text=True, encoding="cp850",
            timeout=10,
        )
        output = result.stdout
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        log.warning("ipconfig failed: %s", exc)
        return []

    adapters: list[NetworkAdapter] = []
    current: Optional[NetworkAdapter] = None

    for line in output.splitlines():
        # New adapter section
        adapter_match = re.match(r"^([A-Za-z].+?):$", line)
        if adapter_match:
            if current:
                adapters.append(current)
            name = adapter_match.group(1).strip()
            current = NetworkAdapter(name=name)
            continue

        if current is None:
            continue

        # Description
        if re.search(r"Description\s*[:.]", line, re.I):
            val = line.split(":", 1)[-1].strip()
            if val:
                current.description = val

        # MAC
        elif re.search(r"Physical Address\s*[:.]", line, re.I):
            val = line.split(":", 1)[-1].strip()
            current.mac = val

        # IPv4
        elif re.search(r"IPv4 Address\s*[:.]", line, re.I):
            ip = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if ip:
                current.ip_addresses.append(ip.group(1))

        # Subnet
        elif re.search(r"Subnet Mask\s*[:.]", line, re.I):
            ip = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if ip:
                current.subnet_masks.append(ip.group(1))

        # Gateway
        elif re.search(r"Default Gateway\s*[:.]", line, re.I):
            ip = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if ip:
                current.gateways.append(ip.group(1))

        # Media state
        elif re.search(r"Media State\s*[:.]", line, re.I):
            current.is_connected = "disconnected" not in line.lower()

    if current:
        adapters.append(current)

    return adapters


# ─────────────────────────────────────────────────────────────────────────────
# WMI-enhanced adapter list (optional, Windows only)
# ─────────────────────────────────────────────────────────────────────────────

def _query_via_wmi() -> Optional[list[NetworkAdapter]]:
    """
    Try to get adapter info via WMI (pywin32).
    Returns None if pywin32 is not installed or we're not on Windows.
    """
    if not IS_WINDOWS:
        return None
    try:
        import wmi  # type: ignore
        c = wmi.WMI()
        adapters: list[NetworkAdapter] = []
        for nic in c.Win32_NetworkAdapterConfiguration(IPEnabled=True):
            adapter = NetworkAdapter(
                name=nic.Description or "Unknown",
                description=nic.Description or "",
                mac=nic.MACAddress or "",
                ip_addresses=list(nic.IPAddress or []),
                subnet_masks=list(nic.IPSubnet or []),
                gateways=list(nic.DefaultIPGateway or []),
                interface_index=nic.InterfaceIndex or -1,
            )
            adapters.append(adapter)
        return adapters
    except Exception as exc:
        log.debug("WMI query failed (pywin32 not installed?): %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def list_adapters(use_wmi: bool = True) -> list[NetworkAdapter]:
    """
    Return all active IPv4 network adapters.

    Tries WMI first (more metadata, Windows-only), then falls back to
    ipconfig parsing (always available).
    """
    if use_wmi and IS_WINDOWS:
        wmi_result = _query_via_wmi()
        if wmi_result:
            return wmi_result

    return _parse_ipconfig()


def find_router_adapter(
    router_ip: str = "192.168.31.1",
    adapters: Optional[list[NetworkAdapter]] = None,
) -> Optional[NetworkAdapter]:
    """
    Return the network adapter whose IP is in the same /24 subnet as *router_ip*.
    If multiple adapters match, the first one is returned.
    """
    if adapters is None:
        adapters = list_adapters()

    subnet_prefix = ".".join(router_ip.split(".")[:3]) + "."
    log.info("Looking for adapter in subnet %s0/24…", subnet_prefix)

    for adapter in adapters:
        if adapter.has_ip_in_subnet(subnet_prefix):
            log.info("Found adapter: %s", adapter)
            return adapter

    log.warning("No adapter found in subnet %s0/24.", subnet_prefix)
    return None


def get_local_ip_for_router(router_ip: str = "192.168.31.1") -> str:
    """
    Return this machine's IP address on the interface used to reach *router_ip*.
    Uses UDP socket trick (no actual connection made).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((router_ip, 80))
            return s.getsockname()[0]
    except OSError:
        return "0.0.0.0"


def print_adapters(adapters: Optional[list[NetworkAdapter]] = None) -> None:
    """Pretty-print all detected adapters to stdout."""
    if adapters is None:
        adapters = list_adapters()
    print("\n  Active Network Adapters:")
    print("  " + "─" * 50)
    for i, a in enumerate(adapters):
        ips = ", ".join(a.ip_addresses) if a.ip_addresses else "no IPv4"
        connected = "✔" if a.is_connected else "✘"
        print(f"  [{i}] {connected} {a.name}")
        if a.description and a.description != a.name:
            print(f"       {a.description}")
        print(f"       IP : {ips}")
        if a.mac:
            print(f"       MAC: {a.mac}")
    print()


def prompt_select_adapter(
    adapters: Optional[list[NetworkAdapter]] = None,
) -> Optional[NetworkAdapter]:
    """
    Interactive prompt to let the user select a network adapter.
    Returns the selected adapter or None on cancel.
    """
    if adapters is None:
        adapters = list_adapters()
    if not adapters:
        print("  No network adapters found.")
        return None

    print_adapters(adapters)
    while True:
        choice = input(f"  Select adapter [0-{len(adapters)-1}] or 'q' to cancel: ").strip()
        if choice.lower() == "q":
            return None
        try:
            idx = int(choice)
            if 0 <= idx < len(adapters):
                return adapters[idx]
        except ValueError:
            pass
        print("  Invalid selection, try again.")


# ─────────────────────────────────────────────────────────────────────────────
# Windows Firewall helper (callable standalone)
# ─────────────────────────────────────────────────────────────────────────────

def add_firewall_rule(
    name: str,
    port: int,
    direction: str = "Inbound",
    protocol: str = "TCP",
) -> bool:
    """
    Add a Windows Firewall Allow rule via netsh.
    Returns True on success (or if rule already exists).
    Requires Administrator privileges.
    """
    if not IS_WINDOWS:
        return True   # No-op on Linux/macOS

    cmd = [
        "netsh", "advfirewall", "firewall", "add", "rule",
        f"name={name}",
        f"dir={direction.lower()}",
        "action=allow",
        f"protocol={protocol}",
        f"localport={port}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 or "FAILED" not in result.stderr.upper():
            log.info("Firewall rule '%s' added/verified (port %d %s).", name, port, direction)
            return True
    except subprocess.SubprocessError as exc:
        log.warning("Could not add firewall rule '%s': %s", name, exc)
    return False


def setup_installer_firewall_rules() -> None:
    """Add all required firewall rules for the installer (FTP + Telnet)."""
    rules = [
        ("OpenWRT-Telnet-Out", 23, "Outbound",  "TCP"),
        ("OpenWRT-FTP-Cmd",   21, "Outbound",  "TCP"),
        ("OpenWRT-FTP-In",    21, "Inbound",   "TCP"),
    ]
    for name, port, direction, proto in rules:
        add_firewall_rule(name, port, direction, proto)
