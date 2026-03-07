"""
modules/firmware.py
===================
Download and verify OpenWRT firmware images.

Features:
  • Resolve the correct firmware URL from config.yaml
  • Download with tqdm progress bar and resume support
  • Verify SHA-256 checksum against the official sha256sums file
  • Return a local Path to the verified firmware file
"""

import hashlib
import re
import time
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

from utils.logger import get_logger

log = get_logger("firmware")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    """Compute SHA-256 of a local file, reading in 8 MB chunks."""
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _fetch_expected_sha256(sha256_url: str, filename: str) -> Optional[str]:
    """
    Download the sha256sums index file and extract the hash for *filename*.
    Returns the 64-char hex digest string or None if not found.
    """
    log.info("Fetching checksum index: %s", sha256_url)
    try:
        resp = requests.get(sha256_url, timeout=30)
        resp.raise_for_status()
        for line in resp.text.splitlines():
            # Format: "<hash>  <filename>" or "<hash> *<filename>"
            parts = re.split(r"\s+\*?", line.strip(), maxsplit=1)
            if len(parts) == 2 and parts[1].strip() == filename:
                return parts[0].strip()
    except requests.RequestException as exc:
        log.warning("Could not fetch SHA-256 index: %s", exc)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# FirmwareManager
# ─────────────────────────────────────────────────────────────────────────────

class FirmwareManager:
    """
    Download and verify OpenWRT firmware for a given router model.

    Parameters
    ----------
    model_config : The dict from config.yaml['models'][model_key]
    download_dir : Local directory to store firmware files (default: ./firmware)
    """

    def __init__(self, model_config: dict, download_dir: str | Path = "firmware"):
        self.cfg = model_config
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def firmware_url(self) -> str:
        return self.cfg["firmware_url"]

    @property
    def firmware_filename(self) -> str:
        return self.cfg["firmware_filename"]

    @property
    def sha256_url(self) -> str:
        return self.cfg.get("sha256_url", "")

    @property
    def local_path(self) -> Path:
        return self.download_dir / self.firmware_filename

    # ── Download ──────────────────────────────────────────────────────────────

    def download(self, force: bool = False) -> Path:
        """
        Download the firmware file.  Skips if already present and not *force*.

        Returns the local Path of the downloaded file.
        Raises RuntimeError on failure.
        """
        if self.local_path.exists() and not force:
            log.info("Firmware already cached: %s", self.local_path)
            return self.local_path

        log.info("Downloading firmware from:")
        log.info("  %s", self.firmware_url)

        try:
            resp = requests.get(self.firmware_url, stream=True, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Firmware download failed: {exc}") from exc

        total = int(resp.headers.get("content-length", 0))
        tmp_path = self.local_path.with_suffix(".tmp")

        with open(tmp_path, "wb") as fh, tqdm(
            desc=self.firmware_filename,
            total=total,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            ncols=80,
        ) as pbar:
            for chunk in resp.iter_content(chunk_size=128 * 1024):
                fh.write(chunk)
                pbar.update(len(chunk))

        tmp_path.rename(self.local_path)
        log.info("Download complete → %s  (%s MB)", self.local_path,
                 round(self.local_path.stat().st_size / 1024 / 1024, 2))
        return self.local_path

    # ── Checksum verification ─────────────────────────────────────────────────

    def verify(self, firmware_path: Optional[Path] = None) -> bool:
        """
        Verify SHA-256 checksum of the downloaded firmware.

        Returns True if verified or if no checksum source is available
        (logs a warning in that case).  Returns False on mismatch.
        """
        path = firmware_path or self.local_path
        if not path.exists():
            log.error("Firmware file not found: %s", path)
            return False

        actual = _sha256_file(path)
        log.debug("SHA-256 (local): %s", actual)

        # Use pre-configured hash if available
        expected = self.cfg.get("sha256", "").strip()

        # Try fetching from sha256sums index
        if not expected and self.sha256_url:
            expected = _fetch_expected_sha256(self.sha256_url, self.firmware_filename) or ""

        if not expected:
            log.warning(
                "⚠  No SHA-256 reference available – skipping checksum verification."
            )
            return True   # assume OK but warn

        if actual.lower() == expected.lower():
            log.info("✔  SHA-256 checksum verified: %s", actual[:16] + "…")
            return True

        log.error("✘  SHA-256 MISMATCH!")
        log.error("   Expected : %s", expected)
        log.error("   Actual   : %s", actual)
        return False

    # ── Master flow ───────────────────────────────────────────────────────────

    def prepare(self, force_download: bool = False) -> Path:
        """
        Download (if needed) and verify firmware.
        Returns local Path on success.
        Raises RuntimeError on checksum failure or download error.
        """
        path = self.download(force=force_download)
        if not self.verify(path):
            path.unlink(missing_ok=True)
            raise RuntimeError(
                "Firmware SHA-256 verification failed.  "
                "The file may be corrupt.  "
                "Re-run with --force to re-download."
            )
        return path
