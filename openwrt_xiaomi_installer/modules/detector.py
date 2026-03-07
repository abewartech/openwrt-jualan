"""
modules/detector.py
===================
Auto-detect the connected Xiaomi router model and firmware version.

Detection flow:
  1. Verify basic connectivity (ping / HTTP to router_ip)
  2. Query the router's web UI for model & firmware version
  3. Distinguish 4A_V1 / 4A_V2 / 4C from the returned data
  4. Return a RouterInfo dataclass consumed by all other modules
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
import yaml

from utils.logger import get_logger
from utils.network import http_get, ping, is_port_open

log = get_logger("detector")


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RouterInfo:
    ip: str
    model_key: str                      # config.yaml key: 4a_gigabit_v1 / v2 / 4c
    display_name: str
    firmware_version: str
    hardware_version: str
    mac: str = ""
    stok: str = ""                      # session token (set after login)
    config: dict = field(default_factory=dict)   # merged from config.yaml


# ─────────────────────────────────────────────────────────────────────────────
# Model fingerprints parsed from router API responses
# ─────────────────────────────────────────────────────────────────────────────

# Regex patterns found in the /api/xqsystem/router_info response
MODEL_PATTERNS = {
    "4a_gigabit": re.compile(r"R4A|4A.*Gigabit|mi4a_.*gigabit", re.I),
    "4c":         re.compile(r"R4C|Mi Router 4C|mi4c", re.I),
}

# Version threshold that separates V1 from V2 for the 4A Gigabit
V2_FIRMWARE_THRESHOLD = (2, 30, 20)


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Convert '2.30.20' → (2, 30, 20).  Returns (0,) on parse failure."""
    try:
        return tuple(int(x) for x in re.findall(r"\d+", version_str))
    except ValueError:
        return (0,)


def _is_v2_firmware(version_str: str) -> bool:
    return _parse_version(version_str) >= V2_FIRMWARE_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# RouterDetector
# ─────────────────────────────────────────────────────────────────────────────

class RouterDetector:
    """
    Detect the Xiaomi router model and firmware version by querying
    the stock web interface.
    """

    STATUS_URL = "http://{ip}/cgi-bin/luci/api/xqsystem/router_info"
    INIT_URL   = "http://{ip}/cgi-bin/luci/api/xqsystem/init_info"

    def __init__(self, router_ip: str, config_path: str = "config.yaml"):
        self.router_ip = router_ip
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0"})
        self._config = self._load_config(config_path)

    # ── Config ────────────────────────────────────────────────────────────────

    @staticmethod
    def _load_config(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return yaml.safe_load(fh)
        except FileNotFoundError:
            log.warning("config.yaml not found at %s – using defaults.", path)
            return {}

    # ── Connectivity ──────────────────────────────────────────────────────────

    def check_connectivity(self) -> bool:
        """Return True if the router is reachable via ping AND HTTP."""
        log.info("Checking connectivity to %s…", self.router_ip)
        if not ping(self.router_ip):
            log.error("Ping to %s failed.  Is the LAN cable connected?", self.router_ip)
            return False
        if not is_port_open(self.router_ip, 80, timeout=5):
            log.error("HTTP port 80 on %s is closed.", self.router_ip)
            return False
        log.info("Router at %s is reachable.", self.router_ip)
        return True

    # ── API query ─────────────────────────────────────────────────────────────

    def _get_router_info_api(self) -> Optional[dict]:
        """Query /api/xqsystem/router_info (works without auth)."""
        url = self.STATUS_URL.format(ip=self.router_ip)
        resp = http_get(url, timeout=10, session=self.session)
        if resp is None:
            return None
        try:
            data = resp.json()
            if data.get("code") == 0:
                return data
        except ValueError:
            pass
        return None

    def _get_init_info(self) -> Optional[dict]:
        """Query /api/xqsystem/init_info as fallback."""
        url = self.INIT_URL.format(ip=self.router_ip)
        resp = http_get(url, timeout=10, session=self.session)
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    # ── Model identification ──────────────────────────────────────────────────

    def _identify_model(self, info: dict) -> tuple[str, str]:
        """
        Return (model_key, display_name) from parsed router_info JSON.
        Falls back to prompting or 4a_gigabit_v1 if unsure.
        """
        # The API returns fields like:
        #   {"routerName": "MiRouter 4A Gigabit", "romVersion": "2.30.20", ...}
        router_name = str(info.get("routerName", "") or info.get("model", ""))
        fw_version   = str(info.get("romVersion", "") or info.get("firmware", "0"))

        log.debug("Raw router_name=%r  fw_version=%r", router_name, fw_version)

        models_cfg = self._config.get("models", {})

        if MODEL_PATTERNS["4c"].search(router_name):
            key = "4c"
        elif MODEL_PATTERNS["4a_gigabit"].search(router_name):
            if _is_v2_firmware(fw_version):
                key = "4a_gigabit_v2"
            else:
                key = "4a_gigabit_v1"
        else:
            log.warning("Unrecognised router name: %r", router_name)
            key = self._prompt_model_choice()

        display = models_cfg.get(key, {}).get("display_name", key)
        return key, display

    @staticmethod
    def _prompt_model_choice() -> str:
        """Interactive prompt when auto-detect fails."""
        print("\n⚠  Could not auto-detect router model.  Please select:")
        print("  1) Xiaomi Mi Router 4A Gigabit V1 (firmware < 2.30.20)")
        print("  2) Xiaomi Mi Router 4A Gigabit V2 (firmware ≥ 2.30.20)")
        print("  3) Xiaomi Mi Router 4C")
        while True:
            choice = input("Enter choice [1/2/3]: ").strip()
            if choice == "1":
                return "4a_gigabit_v1"
            if choice == "2":
                return "4a_gigabit_v2"
            if choice == "3":
                return "4c"
            print("Invalid choice, try again.")

    # ── Public interface ──────────────────────────────────────────────────────

    def detect(self) -> RouterInfo:
        """
        Full detection pipeline.
        Raises RuntimeError if router is unreachable.
        """
        if not self.check_connectivity():
            raise RuntimeError(
                f"Router at {self.router_ip} is not reachable.  "
                "Ensure LAN cable is connected and IP is correct."
            )

        # Try primary API
        info = self._get_router_info_api()
        if info is None:
            log.warning("Primary router_info API failed, trying init_info…")
            info = self._get_init_info() or {}

        fw_version  = str(info.get("romVersion") or info.get("firmware") or "unknown")
        hw_version  = str(info.get("hardVersion") or info.get("hardware") or "unknown")
        mac         = str(info.get("mac") or "")

        model_key, display_name = self._identify_model(info)
        model_config = self._config.get("models", {}).get(model_key, {})

        router_info = RouterInfo(
            ip=self.router_ip,
            model_key=model_key,
            display_name=display_name,
            firmware_version=fw_version,
            hardware_version=hw_version,
            mac=mac,
            config=model_config,
        )

        log.info("─" * 60)
        log.info("Detected router  : %s", display_name)
        log.info("Firmware version : %s", fw_version)
        log.info("Hardware version : %s", hw_version)
        log.info("MAC address      : %s", mac)
        log.info("Config key       : %s", model_key)
        log.info("─" * 60)

        return router_info
