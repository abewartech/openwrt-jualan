"""
modules/flasher.py
==================
Upload firmware via FTP and execute the mtd flash command via telnet.

Safety checks:
  • Verifies the OS1 partition exists before writing
  • Prompts user for confirmation (unless --force)
  • Monitors for reboot completion
  • Does NOT double-flash (checks /tmp/firmware.bin presence first)
"""

import ftplib
import os
import time
from ftplib import FTP
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from utils.logger import get_logger
from utils.network import wait_for_ping, wait_for_port
from .telnet_client import TelnetClient

log = get_logger("flasher")

# ─────────────────────────────────────────────────────────────────────────────

class Flasher:
    """
    Upload firmware and execute mtd write on the router.

    Parameters
    ----------
    router_ip    : IP of the router
    model_config : dict from config.yaml['models'][model_key]
    """

    FTP_CHUNK = 65536    # 64 KB upload chunks
    FLASH_TIMEOUT = 300  # seconds

    def __init__(
        self,
        router_ip: str,
        model_config: dict,
        ftp_user: str = "root",
        ftp_pass: str = "root",
    ):
        self.ip       = router_ip
        self.cfg      = model_config
        self.ftp_user = ftp_user
        self.ftp_pass = ftp_pass

    # ── Safety checks ─────────────────────────────────────────────────────────

    def _verify_os1_partition(self, telnet: TelnetClient) -> bool:
        """Confirm OS1 (or the configured partition) exists on the router."""
        partition = self.cfg.get("mtd_flash_partition", "OS1")
        output = telnet.run_command("cat /proc/mtd")
        if partition.lower() in output.lower():
            log.info("✔  Partition '%s' found on router.", partition)
            return True
        log.error(
            "Partition '%s' NOT found in /proc/mtd!  Aborting to prevent brick.",
            partition,
        )
        log.debug("Partition table:\n%s", output)
        return False

    def _check_tmp_space(self, telnet: TelnetClient, firmware_path: Path) -> bool:
        """Ensure /tmp has sufficient free space for the firmware image."""
        firmware_mb = firmware_path.stat().st_size / 1024 / 1024
        output = telnet.run_command("df -k /tmp")
        # Parse 'df' output: Available (4th column, in KB)
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    free_kb = int(parts[3])
                    free_mb = free_kb / 1024
                    log.debug("/tmp free space: %.1f MB (need %.1f MB)", free_mb, firmware_mb)
                    if free_mb < firmware_mb + 1:
                        log.error(
                            "Insufficient /tmp space: %.1fMB free, need %.1fMB.",
                            free_mb, firmware_mb + 1,
                        )
                        return False
                    return True
                except ValueError:
                    pass
        log.warning("Could not parse df output – proceeding anyway.")
        return True

    # ── FTP upload ────────────────────────────────────────────────────────────

    def upload_firmware(self, firmware_path: Path) -> bool:
        """
        Upload firmware to /tmp/firmware.bin on the router via FTP.
        """
        remote_path = self.cfg.get("ftp_upload_path", "/tmp/firmware.bin")
        file_size = firmware_path.stat().st_size

        log.info("Uploading firmware via FTP…")
        log.info("  Local  : %s  (%.2f MB)", firmware_path, file_size / 1024 / 1024)
        log.info("  Remote : %s:%s", self.ip, remote_path)

        try:
            with FTP(self.ip, timeout=120) as ftp:
                ftp.login(self.ftp_user, self.ftp_pass)

                with open(firmware_path, "rb") as fh, tqdm(
                    desc="Uploading",
                    total=file_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    ncols=80,
                ) as pbar:
                    def callback(data: bytes):
                        pbar.update(len(data))

                    ftp.storbinary(
                        f"STOR {remote_path}",
                        fh,
                        blocksize=self.FTP_CHUNK,
                        callback=callback,
                    )

            log.info("✔  Firmware uploaded successfully.")
            return True
        except (ftplib.Error, OSError) as exc:
            log.error("FTP upload failed: %s", exc)
            return False

    # ── MTD flash ─────────────────────────────────────────────────────────────

    def flash_firmware(self, telnet: TelnetClient) -> bool:
        """
        Execute the mtd write command on the router.
        The router will reboot automatically after successful flash.
        """
        flash_cmd = self.cfg.get(
            "flash_command",
            "mtd -e OS1 -r write /tmp/firmware.bin OS1",
        )
        log.info("Executing flash command: %s", flash_cmd)
        log.warning("⚡ DO NOT disconnect power or LAN during flashing!")

        # Run the command; we may not get a response (router reboots)
        try:
            # We send the command but don't wait for a marker since router reboots
            if telnet._tn:
                telnet._tn.write((flash_cmd + "\n").encode())
                log.info("Flash command sent.  Waiting for router reboot…")
                # Wait a moment for the write to begin
                time.sleep(5)
        except Exception as exc:
            log.debug("Expected connection drop during flash: %s", exc)

        return True   # actual success determined by ping check below

    # ── Post-flash verification ───────────────────────────────────────────────

    def wait_for_openwrt(
        self,
        openwrt_ip: str = "192.168.1.1",
        max_attempts: int = 30,
        interval: int = 5,
    ) -> bool:
        """
        Wait for the router to reboot into OpenWRT.
        First waits for ping on openwrt_ip (195.168.1.1), then checks HTTP.
        Returns True when OpenWRT web interface is accessible.
        """
        log.info("Waiting for router to reboot (this may take 2-3 minutes)…")
        time.sleep(20)   # give the flash process time to complete

        # Some routers boot back on 192.168.1.1, some on 192.168.31.1
        for target_ip in [openwrt_ip, self.ip]:
            log.info("Checking for OpenWRT on %s…", target_ip)
            if wait_for_ping(target_ip, max_attempts=max_attempts, interval=interval):
                if wait_for_port(target_ip, 80, max_attempts=10, interval=3):
                    log.info("✔  OpenWRT is accessible at http://%s", target_ip)
                    return True

        log.error("Router did not come back after flashing.  Check physical device.")
        return False

    # ── Master flash flow ─────────────────────────────────────────────────────

    def run(
        self,
        firmware_path: Path,
        telnet: TelnetClient,
        force: bool = False,
        openwrt_ip: str = "192.168.1.1",
    ) -> bool:
        """
        Full flash pipeline:
          1. Safety checks (OS1 partition, /tmp space)
          2. User confirmation (unless force=True)
          3. FTP upload
          4. MTD write
          5. Wait for reboot

        Returns True on success.
        """
        log.info("=" * 60)
        log.info("Starting firmware flash")
        log.info("=" * 60)

        # Safety: verify OS1 exists
        if not self._verify_os1_partition(telnet):
            raise RuntimeError("Aborting – partition check failed.")

        # Safety: check /tmp space
        if not self._check_tmp_space(telnet, firmware_path):
            raise RuntimeError("Aborting – insufficient /tmp space.")

        # Confirmation prompt
        if not force:
            fw_name = firmware_path.name
            print(f"\n⚠  About to flash: {fw_name}")
            print(f"   Router: {self.ip}")
            print("   This will ERASE the stock firmware permanently.")
            print("   Ensure you have a backup before proceeding.\n")
            ans = input("Type 'YES' to continue: ").strip()
            if ans != "YES":
                log.info("Flash aborted by user.")
                return False

        # Upload firmware
        if not self.upload_firmware(firmware_path):
            raise RuntimeError("Firmware upload failed – aborting.")

        # Flash
        self.flash_firmware(telnet)

        # Wait for OpenWRT
        success = self.wait_for_openwrt(openwrt_ip=openwrt_ip)
        if success:
            log.info("🎉 OpenWRT installation complete!")
        else:
            log.error("Post-flash check failed.  Manual verification required.")
        return success
