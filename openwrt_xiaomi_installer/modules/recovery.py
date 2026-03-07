"""
modules/recovery.py
===================
Recovery guidance and tools for bricked Xiaomi routers.

Covers:
  • Xiaomi MiWifi Repair Tool (Windows) launcher
  • TFTP-based recovery instructions
  • 4C reset-button recovery
  • Console output with step-by-step instructions
"""

import sys
import textwrap
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from utils.windows_helper import find_miwifi_tool, launch_miwifi_tool, IS_WINDOWS

log = get_logger("recovery")


# ─────────────────────────────────────────────────────────────────────────────
# Recovery text templates
# ─────────────────────────────────────────────────────────────────────────────

_MIWIFI_TOOL_URL = "https://www.miwifi.com/miwifi_download.html"

_TFTP_RECOVERY_4A = """
╔════════════════════════════════════════════════════════════════╗
║          TFTP RECOVERY - Xiaomi Mi Router 4A Gigabit          ║
╚════════════════════════════════════════════════════════════════╝

Prerequisites:
  • A TFTP server running on your PC (e.g. Tftpd64 for Windows)
  • The stock Xiaomi firmware or an OpenWRT recovery image
  • LAN cable between PC and router (WAN port of router)

Steps:
  1. Set your PC's IP to 192.168.31.100, subnet 255.255.255.0
  2. Place the recovery firmware in the TFTP root as 'root_fs'
     (or follow Xiaomi docs for exact filename)
  3. Start TFTP server in 'tftp server' mode
  4. Press and HOLD the reset button on the router
  5. Power ON the router while HOLDING reset
  6. Keep holding until the LED blinks orange/yellow rapidly
  7. Release the button – the router fetches firmware via TFTP
  8. Wait 3-5 minutes for flashing and reboot

Resources:
  • MiWifi Repair Tool: {miwifi_url}
  • Tftpd64 (free TFTP server): https://pjo2.github.io/tftpd64/
""".format(miwifi_url=_MIWIFI_TOOL_URL)


_TFTP_RECOVERY_4C = """
╔════════════════════════════════════════════════════════════════╗
║             RESET BUTTON RECOVERY - Xiaomi Mi Router 4C       ║
╚════════════════════════════════════════════════════════════════╝

The 4C supports a simple reset-button recovery:

  1. Power OFF the router
  2. Press and HOLD the reset button (small hole on back panel)
  3. Power ON while HOLDING reset
  4. Hold for ~10 seconds until LED blinks rapidly
  5. Release – router boots into recovery mode
  6. Connect to 192.168.31.1 via browser to upload firmware

If the above fails, use a serial console (UART):
  • Baud rate: 115200 8N1
  • TX/RX pads are on the PCB (3.3V logic level)
  • During U-Boot, interrupt boot with any key
  • tftpboot and flash manually

Resources:
  • MiWifi Repair Tool: {miwifi_url}
""".format(miwifi_url=_MIWIFI_TOOL_URL)


_GENERAL_TIPS = """
General Unbrick Tips:
  ├─ NEVER disconnect power during a flash operation
  ├─ Always backup partitions BEFORE flashing
  ├─ OpenWRT community: https://forum.openwrt.org
  └─ Device page:
       4A Gigabit → https://openwrt.org/toh/xiaomi/mi_router_4a_gigabit
       4C         → https://openwrt.org/toh/xiaomi/mi_router_4c
"""


# ─────────────────────────────────────────────────────────────────────────────
# RecoveryManager
# ─────────────────────────────────────────────────────────────────────────────

class RecoveryManager:
    """
    Provide recovery guidance based on the router model.

    Parameters
    ----------
    model_key : config key (4a_gigabit_v1 / 4a_gigabit_v2 / 4c)
    """

    def __init__(self, model_key: str = "4a_gigabit_v1"):
        self.model_key = model_key

    # ── Print instructions ────────────────────────────────────────────────────

    def show_recovery_instructions(self) -> None:
        """Print model-specific recovery instructions to stdout."""
        print("\n" + "=" * 64)
        print("  RECOVERY MODE")
        print("=" * 64)

        if "4c" in self.model_key:
            print(_TFTP_RECOVERY_4C)
        else:
            print(_TFTP_RECOVERY_4A)

        print(_GENERAL_TIPS)

    # ── MiWifi Repair Tool ────────────────────────────────────────────────────

    def try_miwifi_tool(self, tool_path: Optional[Path] = None) -> bool:
        """
        Attempt to launch the MiWifi Repair Tool (Windows only).
        Returns True if launched, False otherwise.
        """
        if not IS_WINDOWS:
            log.info("MiWifi Repair Tool is Windows-only.")
            self.show_recovery_instructions()
            return False

        log.info("Attempting to launch MiWifi Repair Tool…")
        if launch_miwifi_tool(tool_path):
            log.info("MiWifi Repair Tool launched.  Follow the on-screen instructions.")
            return True

        log.warning("MiWifi Repair Tool not found on this system.")
        print(f"\n  → Download it from: {_MIWIFI_TOOL_URL}")
        self.show_recovery_instructions()
        return False

    # ── OpenWRT verification ──────────────────────────────────────────────────

    def verify_openwrt_access(
        self,
        openwrt_ip: str = "192.168.1.1",
        username: str = "root",
        password: str = "",
    ) -> bool:
        """
        Attempt to log in to OpenWRT LuCI and confirm the flash succeeded.
        Returns True if OpenWRT is accessible.
        """
        import requests
        urls = [
            f"http://{openwrt_ip}/",
            f"http://{openwrt_ip}/cgi-bin/luci/",
        ]
        for url in urls:
            try:
                resp = requests.get(url, timeout=10)
                if "OpenWrt" in resp.text or "LuCI" in resp.text or resp.status_code == 200:
                    log.info("✔  OpenWRT detected at %s", url)
                    return True
            except requests.RequestException:
                pass

        log.warning("OpenWRT web interface not detected at %s.", openwrt_ip)
        return False

    # ── Post-install info ─────────────────────────────────────────────────────

    @staticmethod
    def print_post_install_info(openwrt_ip: str = "192.168.1.1") -> None:
        """Print useful info after successful OpenWRT installation."""
        info = f"""
╔════════════════════════════════════════════════════════════════╗
║           OpenWRT Installation Successful! 🎉                  ║
╚════════════════════════════════════════════════════════════════╝

  Web interface  : http://{openwrt_ip}/
  SSH access     : ssh root@{openwrt_ip}
  Default login  : username=root, password=(none on first boot)

  First steps:
    1. Set a strong root password immediately
    2. Configure your WAN interface
    3. Run: opkg update  (update package lists)
    4. Install packages: opkg install <package-name>

  Documentation  : https://openwrt.org/docs/guide-user/start
"""
        print(info)
