#!/usr/bin/env python3
"""
openwrt_installer.py
====================
Main entry point for the OpenWRT Xiaomi Auto-Installer.

Supports:
  • Xiaomi Mi Router 4A Gigabit V1 (firmware < 2.30.20)
  • Xiaomi Mi Router 4A Gigabit V2 (firmware ≥ 2.30.20)
  • Xiaomi Mi Router 4C

Usage:
  python openwrt_installer.py [OPTIONS]

Options:
  --model       {auto,4a_v1,4a_v2,4c}   Router model (default: auto)
  --ip          <IP>                     Router IP     (default: 192.168.31.1)
  --password    <PASSWORD>              Admin password (default: try common ones)
  --backup-only                          Only backup partitions, skip flashing
  --no-backup                            Skip backup step
  --force                                Skip confirmation prompts, re-download firmware
  --verbose                              Enable DEBUG logging to console
  --recovery                             Launch recovery / unbrick tools
  --openwrt-ip  <IP>                     Expected OpenWRT IP after flash (default: 192.168.1.1)
  --fw-dir      <DIR>                    Firmware cache directory (default: ./firmware)
  --backup-dir  <DIR>                    Backup output directory   (default: ./backups)
"""

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Callable, Optional

import yaml

# ---- Local imports ----------------------------------------------------------
from utils.logger import setup_logger, get_logger
from utils.windows_helper import enable_ansi_colors, warn_if_not_admin
from modules.detector import RouterDetector, RouterInfo
from modules.exploit import ExploitManager
from modules.firmware import FirmwareManager
from modules.backup import BackupManager
from modules.flasher import Flasher
from modules.recovery import RecoveryManager
from modules.telnet_client import TelnetClient

# ---------------------------------------------------------------------------
# Config path: works both as a .py script AND as a PyInstaller .exe
# ---------------------------------------------------------------------------

def _get_base_dir() -> Path:
    """
    When frozen by PyInstaller, __file__ is inside a temp directory.
    sys.executable points to the actual .exe location.
    When running as a normal script, use __file__.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # PyInstaller bundles data files next to the exe
        return Path(sys.executable).parent
    return Path(__file__).parent


BASE_DIR           = _get_base_dir()
CONFIG_PATH        = BASE_DIR / "config.yaml"
DEFAULT_ROUTER_IP  = "192.168.31.1"
DEFAULT_OPENWRT_IP = "192.168.1.1"
MODEL_MAP = {
    "4a_v1": "4a_gigabit_v1",
    "4a_v2": "4a_gigabit_v2",
    "4c":    "4c",
    "auto":  "auto",
}


# ─────────────────────────────────────────────────────────────────────────────
# Argument parser
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OpenWRT Auto-Installer for Xiaomi Mi Router 4A Gigabit / 4C",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--model",
        choices=list(MODEL_MAP.keys()),
        default="auto",
        help="Router model (default: auto-detect)",
    )
    p.add_argument(
        "--ip",
        default=DEFAULT_ROUTER_IP,
        metavar="IP",
        help=f"Router LAN IP (default: {DEFAULT_ROUTER_IP})",
    )
    p.add_argument(
        "--password",
        default="",
        metavar="PASSWORD",
        help="Stock admin password (leave blank to try common ones)",
    )
    p.add_argument(
        "--backup-only",
        action="store_true",
        help="Only backup partitions; skip firmware flash",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip partition backup (NOT recommended)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts and re-download firmware",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG output on console",
    )
    p.add_argument(
        "--recovery",
        action="store_true",
        help="Show recovery instructions / launch MiWifi Repair Tool",
    )
    p.add_argument(
        "--openwrt-ip",
        default=DEFAULT_OPENWRT_IP,
        metavar="IP",
        help=f"Expected OpenWRT IP after flash (default: {DEFAULT_OPENWRT_IP})",
    )
    p.add_argument(
        "--fw-dir",
        default="firmware",
        metavar="DIR",
        help="Directory to cache downloaded firmware (default: ./firmware)",
    )
    p.add_argument(
        "--backup-dir",
        default="backups",
        metavar="DIR",
        help="Directory to store partition backups (default: ./backups)",
    )
    return p


# ─────────────────────────────────────────────────────────────────────────────
# Config loader
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"[ERROR] config.yaml not found at: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ─────────────────────────────────────────────────────────────────────────────
# Pretty banner
# ─────────────────────────────────────────────────────────────────────────────

def print_banner() -> None:
    print("""
╔══════════════════════════════════════════════════════════════╗
║     OpenWRT Auto-Installer for Xiaomi Routers               ║
║     Supports: Mi Router 4A Gigabit (V1/V2) & 4C            ║
║     Based on OpenWRTInvasion exploit                        ║
╚══════════════════════════════════════════════════════════════╝
""")


# ─────────────────────────────────────────────────────────────────────────────
# Main installation pipeline
# ─────────────────────────────────────────────────────────────────────────────

def run_install(
    args: argparse.Namespace,
    cfg: dict,
    log: logging.Logger,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> int:
    """
    Full installation pipeline.
    Returns 0 on success, non-zero on failure.
    progress_callback(step, description) is called at each stage (for GUI).
    """

    def _progress(step: int, desc: str = "") -> None:
        if progress_callback:
            progress_callback(step, desc)

    # ── Step 1: Detect router ─────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 1: Router Detection")
    log.info("─" * 60)

    detector = RouterDetector(router_ip=args.ip, config_path=str(CONFIG_PATH))

    if args.model == "auto":
        try:
            router: RouterInfo = detector.detect()
        except RuntimeError as exc:
            log.error("Detection failed: %s", exc)
            return 1
    else:
        # Manual model override
        if not detector.check_connectivity():
            log.error("Router at %s is not reachable.", args.ip)
            return 1
        model_key = MODEL_MAP[args.model]
        model_cfg  = cfg.get("models", {}).get(model_key, {})
        from modules.detector import RouterInfo
        router = RouterInfo(
            ip=args.ip,
            model_key=model_key,
            display_name=model_cfg.get("display_name", model_key),
            firmware_version="unknown",
            hardware_version="unknown",
            config=model_cfg,
        )
        log.info("Using manually specified model: %s", router.display_name)

    # ── Step 2: Exploit – enable telnet & FTP ────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 2: OpenWRTInvasion Exploit")
    log.info("─" * 60)

    exploit = ExploitManager(router_ip=args.ip, admin_password=args.password)
    try:
        result = exploit.run()
    except RuntimeError as exc:
        log.error("Exploit failed: %s", exc)
        recovery = RecoveryManager(model_key=router.model_key)
        recovery.show_recovery_instructions()
        return 2

    router.stok = result["stok"]
    log.info("Exploit complete: telnet=%s  ftp=%s", result["telnet_ok"], result["ftp_ok"])

    # ── Step 3: Telnet login ──────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 3: Telnet Connection")
    log.info("─" * 60)

    telnet_cfg  = cfg.get("router_defaults", {})
    telnet_user = telnet_cfg.get("username", "root")
    telnet_pass = telnet_cfg.get("password", "root")

    telnet = TelnetClient(
        host=args.ip,
        username=telnet_user,
        password=telnet_pass,
        timeout=telnet_cfg.get("timeouts", {}).get("telnet", 30),
    )
    try:
        telnet.connect()
    except Exception as exc:
        log.error("Telnet connection failed: %s", exc)
        return 3

    # ── Step 4: Backup ────────────────────────────────────────────────────────
    if not args.no_backup:
        log.info("─" * 60)
        log.info("STEP 4: Partition Backup")
        log.info("─" * 60)
        backup_mgr = BackupManager(
            router_ip=args.ip,
            model_config=router.config,
            backup_dir=Path(args.backup_dir),
            ftp_user=telnet_user,
            ftp_pass=telnet_pass,
        )
        manifest = backup_mgr.run(telnet)
        if not manifest:
            log.warning("Backup produced no files – check FTP availability.")
    else:
        log.warning("Skipping backup (--no-backup specified).")

    if args.backup_only:
        log.info("✔  Backup-only mode complete.  Exiting.")
        telnet.disconnect()
        return 0

    # ── Step 5: Download & verify firmware ───────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 5: Firmware Download & Verification")
    log.info("─" * 60)

    fw_mgr = FirmwareManager(
        model_config=router.config,
        download_dir=args.fw_dir,
    )
    try:
        firmware_path = fw_mgr.prepare(force_download=args.force)
    except RuntimeError as exc:
        log.error("Firmware preparation failed: %s", exc)
        telnet.disconnect()
        return 4

    # ── Step 6: Flash ─────────────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 6: Flashing OpenWRT")
    log.info("─" * 60)

    flasher = Flasher(
        router_ip=args.ip,
        model_config=router.config,
        ftp_user=telnet_user,
        ftp_pass=telnet_pass,
    )
    try:
        success = flasher.run(
            firmware_path=firmware_path,
            telnet=telnet,
            force=args.force,
            openwrt_ip=args.openwrt_ip,
        )
    except RuntimeError as exc:
        log.error("Flash failed: %s", exc)
        telnet.disconnect()
        recovery = RecoveryManager(model_key=router.model_key)
        recovery.show_recovery_instructions()
        return 5

    telnet.disconnect()

    if not success:
        log.error("Flashing did not complete successfully.")
        recovery = RecoveryManager(model_key=router.model_key)
        recovery.show_recovery_instructions()
        return 6

    # ── Step 7: Post-install verification ────────────────────────────────────
    log.info("─" * 60)
    log.info("STEP 7: Post-Install Verification")
    log.info("─" * 60)

    recovery = RecoveryManager(model_key=router.model_key)
    openwrt_ok = recovery.verify_openwrt_access(openwrt_ip=args.openwrt_ip)
    if openwrt_ok:
        recovery.print_post_install_info(openwrt_ip=args.openwrt_ip)
    else:
        log.warning(
            "OpenWRT web interface not detected at %s.  "
            "The router may need more time or the IP may differ.",
            args.openwrt_ip,
        )

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    enable_ansi_colors()
    print_banner()

    parser = build_parser()
    args   = parser.parse_args()

    # Setup logging
    console_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logger(console_level=console_level)
    log = get_logger("main")

    warn_if_not_admin()

    # Load config
    cfg = load_config(CONFIG_PATH)

    # Recovery-only mode
    if args.recovery:
        model_key = MODEL_MAP.get(args.model, "4a_gigabit_v1") if args.model != "auto" else "4a_gigabit_v1"
        rec = RecoveryManager(model_key=model_key)
        rec.try_miwifi_tool()
        sys.exit(0)

    # Run main installer
    try:
        exit_code = run_install(args, cfg, log)
    except KeyboardInterrupt:
        print("\n\n⚠  Interrupted by user.  If router is mid-flash, DO NOT power off!")
        sys.exit(99)
    except Exception:
        log.critical("Unexpected error:\n%s", traceback.format_exc())
        sys.exit(1)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
