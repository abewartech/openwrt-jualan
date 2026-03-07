"""
modules/backup.py
=================
Backup stock Xiaomi router partitions before flashing OpenWRT.

Operations:
  1. Connect via telnet and list MTD partitions from /proc/mtd
  2. Use `dd` to dump each partition to /tmp/<name>.bin
  3. Download each dump to the local machine via FTP
  4. Save a manifest JSON (filename → MD5 → size)

The backup is STRONGLY recommended before any flashing operation.
"""

import ftplib
import hashlib
import json
import time
from datetime import datetime
from ftplib import FTP
from pathlib import Path
from typing import Optional

from utils.logger import get_logger
from .telnet_client import TelnetClient   # local thin wrapper

log = get_logger("backup")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# BackupManager
# ─────────────────────────────────────────────────────────────────────────────

class BackupManager:
    """
    Backup Xiaomi router flash partitions to local disk.

    Parameters
    ----------
    router_ip   : IP of the router
    model_config: dict from config.yaml['models'][model_key]
    backup_dir  : Local directory to store backups (default: ./backups/<timestamp>)
    """

    def __init__(
        self,
        router_ip: str,
        model_config: dict,
        backup_dir: Optional[Path] = None,
        telnet_user: str = "root",
        telnet_pass: str = "root",
        ftp_user: str = "root",
        ftp_pass: str = "root",
    ):
        self.ip          = router_ip
        self.cfg         = model_config
        self.telnet_user = telnet_user
        self.telnet_pass = telnet_pass
        self.ftp_user    = ftp_user
        self.ftp_pass    = ftp_pass

        if backup_dir is None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = Path("backups") / ts
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # ── MTD partition discovery ───────────────────────────────────────────────

    def list_mtd_partitions(self, telnet: TelnetClient) -> list[dict]:
        """
        Run `cat /proc/mtd` on the router and parse the output.

        Returns a list of dicts:
          [{"dev": "mtd0", "size": "01000000", "erasesize": "00020000", "name": "ALL"}, …]
        """
        log.info("Reading partition table from /proc/mtd…")
        output = telnet.run_command("cat /proc/mtd")
        partitions = []
        for line in output.splitlines():
            # mtd0: 01000000 00020000 "ALL"
            m = __import__("re").match(
                r"(mtd\d+):\s+([0-9a-f]+)\s+([0-9a-f]+)\s+\"(.+)\"",
                line.strip(),
            )
            if m:
                partitions.append({
                    "dev":       m.group(1),
                    "size":      int(m.group(2), 16),
                    "erasesize": int(m.group(3), 16),
                    "name":      m.group(4),
                })
                log.debug("  %s → %s  (%d KB)", m.group(1), m.group(4),
                          int(m.group(2), 16) // 1024)
        return partitions

    # ── DD backup on router ───────────────────────────────────────────────────

    def _backup_partition_on_router(
        self, telnet: TelnetClient, dev: str, dest_filename: str
    ) -> bool:
        """
        Run `dd if=/dev/<dev> of=/tmp/<dest_filename>` on the router.
        Returns True on success.
        """
        dest_path = f"/tmp/{dest_filename}"
        cmd = f"dd if=/dev/{dev} of={dest_path} && echo DONE || echo FAIL"
        log.info("  Backing up /dev/%s → /tmp/%s…", dev, dest_filename)
        output = telnet.run_command(cmd, timeout=120)
        if "DONE" in output:
            log.info("  ✔  dd succeeded for %s", dev)
            return True
        log.error("  dd output: %s", output.strip())
        return False

    # ── FTP download ──────────────────────────────────────────────────────────

    def _ftp_download(self, remote_path: str, local_path: Path) -> bool:
        """Download *remote_path* from router FTP to *local_path*."""
        try:
            with FTP(self.ip, timeout=60) as ftp:
                ftp.login(self.ftp_user, self.ftp_pass)
                with open(local_path, "wb") as fh:
                    ftp.retrbinary(f"RETR {remote_path}", fh.write, blocksize=65536)
            size_mb = local_path.stat().st_size / 1024 / 1024
            log.info("  ✔  Downloaded %s → %s  (%.2f MB)", remote_path, local_path, size_mb)
            return True
        except (ftplib.Error, OSError) as exc:
            log.error("  FTP download failed for %s: %s", remote_path, exc)
            return False

    # ── Delete temp files on router ───────────────────────────────────────────

    def _cleanup_router_tmp(self, telnet: TelnetClient, filenames: list[str]) -> None:
        """Remove temporary backup files from /tmp on the router."""
        for fn in filenames:
            telnet.run_command(f"rm -f /tmp/{fn}")
            log.debug("Removed /tmp/%s from router.", fn)

    # ── Master backup flow ────────────────────────────────────────────────────

    def run(self, telnet: TelnetClient) -> dict:
        """
        Full backup pipeline:
          1. List MTD partitions
          2. dd each configured partition to /tmp
          3. FTP download to local backup_dir
          4. Verify via MD5 and save manifest

        Returns a manifest dict { filename: {md5, size_bytes, dev} }
        """
        log.info("=" * 60)
        log.info("Starting partition backup")
        log.info("Backup directory: %s", self.backup_dir)
        log.info("=" * 60)

        partitions_cfg = self.cfg.get("backup_mtd", [])
        if not partitions_cfg:
            log.warning("No backup_mtd entries in config for this model – skipping backup.")
            return {}

        # Build a map of partition name → /dev/mtdX from /proc/mtd
        available = {p["name"].lower(): p["dev"] for p in self.list_mtd_partitions(telnet)}

        manifest = {}
        tmp_created = []

        for entry in partitions_cfg:
            part_name = entry["name"]
            dest_file = entry["dest"]
            # Prefer /dev/mtdX from /proc/mtd if available, else use source from config
            dev = available.get(part_name.lower()) or entry["source"].lstrip("/")

            # Step 1: dd on router
            ok = self._backup_partition_on_router(telnet, dev, dest_file)
            if not ok:
                log.warning("Skipping %s due to dd failure.", dest_file)
                continue
            tmp_created.append(dest_file)

            # Step 2: FTP download
            local_file = self.backup_dir / dest_file
            dl_ok = self._ftp_download(f"/tmp/{dest_file}", local_file)
            if not dl_ok:
                continue

            # Step 3: MD5 checksum
            md5 = _md5_file(local_file)
            manifest[dest_file] = {
                "partition": part_name,
                "dev":       dev,
                "md5":       md5,
                "size_bytes": local_file.stat().st_size,
            }
            log.info("  MD5[%s] = %s", dest_file, md5)

        # Save manifest
        manifest_path = self.backup_dir / "backup_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.info("Backup manifest saved: %s", manifest_path)

        # Clean up /tmp on router
        self._cleanup_router_tmp(telnet, tmp_created)

        log.info("✔  Backup complete.  %d partition(s) saved.", len(manifest))
        return manifest
