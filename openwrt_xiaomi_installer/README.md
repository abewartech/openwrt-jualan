# OpenWRT Auto-Installer for Xiaomi Routers

Automated Python tool to install OpenWRT on Xiaomi Mi Router **4A Gigabit (V1/V2)** and **4C**.

Based on the [OpenWRTInvasion](https://github.com/acecilia/OpenWRTInvasion) exploit technique.

---

## ⚠️ WARNING

> **Flashing firmware on a router carries risk.**  
> Always create a full partition backup before flashing.  
> A failed flash can brick your router. Read the [Recovery](#recovery--unbrick) section first.

---

## Supported Devices

| Model | Chipset | Flash | RAM | Notes |
|---|---|---|---|---|
| Mi Router 4A Gigabit **V1** | MT7621 | 16 MB | 128 MB | firmware < 2.30.20 |
| Mi Router 4A Gigabit **V2** | MT7621 | 16 MB | 128 MB | firmware ≥ 2.30.20 |
| Mi Router **4C** | MT7628AN | 16 MB | 64 MB | |

---

## Prerequisites

- **Windows 10/11** or Linux/WSL
- Python 3.10+
- LAN cable connecting PC directly to router
- Router must be running stock Xiaomi firmware

### Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

## Quick Start (Windows)

1. Connect LAN cable from PC to router (any LAN port)
2. Double-click **`windows_runner.bat`**

Or from PowerShell / Command Prompt:

```batch
python openwrt_installer.py --model auto
```

---

## Command Line Options

```
python openwrt_installer.py [OPTIONS]

  --model {auto,4a_v1,4a_v2,4c}    Router model (default: auto-detect)
  --ip IP                           Router LAN IP (default: 192.168.31.1)
  --password PASSWORD               Admin password (default: tries common ones)
  --backup-only                     Backup partitions only, skip flash
  --no-backup                       Skip backup step ⚠ NOT recommended
  --force                           Skip confirmations, force re-download
  --verbose                         Show DEBUG output
  --recovery                        Show recovery instructions / MiWifi tool
  --openwrt-ip IP                   Expected OpenWRT IP post-flash (default: 192.168.1.1)
  --fw-dir DIR                      Firmware cache directory (default: ./firmware)
  --backup-dir DIR                  Backup output directory (default: ./backups)
```

### Examples

```bash
# Auto-detect model and install
python openwrt_installer.py

# Manually specify model
python openwrt_installer.py --model 4c

# Backup only (no flash)
python openwrt_installer.py --backup-only

# Custom router IP with admin password
python openwrt_installer.py --ip 192.168.31.1 --password mypassword

# Skip backup, force re-download (no confirmation prompts)
python openwrt_installer.py --no-backup --force --model 4a_v2

# Show recovery/unbrick tools
python openwrt_installer.py --recovery
```

---

## Installation Pipeline

```
 STEP 1  →  Detect router model & firmware version
 STEP 2  →  OpenWRTInvasion exploit (enable telnet + FTP)
 STEP 3  →  Connect via telnet (root:root)
 STEP 4  →  Backup all MTD partitions to local disk via FTP
 STEP 5  →  Download & verify OpenWRT firmware (SHA-256)
 STEP 6  →  Upload firmware via FTP → flash via mtd
 STEP 7  →  Wait for reboot → verify OpenWRT access
```

---

## Firmware Sources (Official OpenWRT 24.10.0)

| Model | Filename |
|---|---|
| 4A Gigabit V1 | `openwrt-24.10.0-ramips-mt7621-xiaomi_mi-router-4a-gigabit-squashfs-sysupgrade.bin` |
| 4A Gigabit V2 | `openwrt-24.10.0-ramips-mt7621-xiaomi_mi-router-4a-gigabit-v2-squashfs-sysupgrade.bin` |
| 4C | `openwrt-24.10.0-ramips-mt76x8-xiaomi_mi-router-4c-squashfs-sysupgrade.bin` |

Downloaded from `https://downloads.openwrt.org/releases/24.10.0/targets/`

---

## Backup

Partitions are backed up to `./backups/<timestamp>/` before flashing:

| File | Description |
|---|---|
| `all.bin` | Full flash dump (all partitions) |
| `Bootloader.bin` | U-Boot bootloader |
| `Config.bin` | NVRAM / configuration partition |
| `OS1.bin` | Primary OS partition (to be replaced) |
| `OS2.bin` | Secondary OS partition |
| `backup_manifest.json` | MD5 checksums + file sizes |

---

## Recovery / Unbrick

### MiWifi Repair Tool (Windows)
```bash
python openwrt_installer.py --recovery
```
Download: https://www.miwifi.com/miwifi_download.html

### TFTP Recovery (4A Gigabit)
1. Set PC IP to `192.168.31.100 / 255.255.255.0`
2. Start TFTP server (e.g. [Tftpd64](https://pjo2.github.io/tftpd64/))
3. Place stock firmware as `root_fs` in TFTP root
4. Hold reset → power on → release when LED blinks

### Reset Button Recovery (4C)
1. Hold reset while powering on (~10 seconds)
2. Connect to `http://192.168.31.1` to upload firmware

---

## Post-Install

```
Web UI   : http://192.168.1.1/
SSH      : ssh root@192.168.1.1  (no password on first boot)
```

**First steps after install:**
1. Set a root password immediately
2. Configure WAN interface  
3. Run `opkg update` in SSH

---

## Project Structure

```
openwrt_xiaomi_installer/
├── openwrt_installer.py      ← Main entry point
├── config.yaml               ← Router model & firmware configuration
├── requirements.txt
├── README.md
├── windows_runner.bat        ← Double-click launcher for Windows
├── modules/
│   ├── detector.py           ← Auto-detect model & firmware version
│   ├── exploit.py            ← OpenWRTInvasion RCE exploit
│   ├── telnet_client.py      ← Telnet session wrapper
│   ├── firmware.py           ← Download & SHA-256 verify firmware
│   ├── backup.py             ← MTD partition backup via FTP
│   ├── flasher.py            ← FTP upload + mtd flash execution
│   └── recovery.py           ← Recovery tools & instructions
└── utils/
    ├── logger.py             ← Rotating log + colored console
    ├── network.py            ← Ping, port check, HTTP helpers
    └── windows_helper.py     ← WSL check, admin check, MiWifi tool
```

---

## Log Files

Logs are written to `openwrt_installer_YYYYMMDD_HHMMSS.log` in the working directory.

---

## License & Disclaimer

This tool is for **personal, educational use only**. You are responsible for complying with local
laws and router warranties. The authors accept no liability for bricked devices.
