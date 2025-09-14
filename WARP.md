# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

OpenWRTInvasion is a root shell exploit toolkit for Xiaomi routers (4A Gigabit, 4A 100M, 4C, 3Gv2, 4Q, miWifi 3C). The project exploits a remote command execution vulnerability to gain root access and enable telnet/SSH/FTP services on vulnerable routers.

## Architecture

The exploit follows a multi-stage attack pattern:

1. **Authentication Stage**: Obtains authentication token (stok) from router's web interface
2. **Payload Delivery**: Creates and uploads malicious tar.gz containing exploit scripts
3. **Command Injection**: Triggers vulnerability through speedtest URL configuration
4. **Service Setup**: Establishes telnet, SSH, and FTP services on the compromised router

### Core Components

- **Main Exploit Scripts**: `remote_command_execution_vulnerability.py` (v1) and `remote_command_execution_vulnerability_v2.py` (v2)
- **Shell Scripts**: `script.sh` and `script_v2.sh` - executed on router to setup services
- **File Servers**: `tcp_file_server.py` and `http_file_server.py` - serve binaries to router during exploit
- **Payload Template**: `speedtest_urls_template.xml` - template for command injection payload
- **Router Setup Scripts**: Various utility scripts for specific router configurations

### Key Differences Between Versions

- **v1**: Uses GitHub or local TCP server for file delivery, supports Mac/Linux only
- **v2**: Uses local HTTP server, includes all binaries in payload, supports Windows with automatic telnet launch

## Common Development Commands

### Running the Exploit

**Version 1 (Original)**:
```powershell
# Install dependencies
pip3 install -r requirements.txt

# Run exploit (Mac/Linux only)
python3 remote_command_execution_vulnerability.py

# Docker method (works on Windows)
docker build -t openwrtinvasion https://github.com/acecilia/OpenWRTInvasion.git
docker run --network host -it openwrtinvasion
```

**Version 2 (Windows-compatible)**:
```powershell
# Install dependencies
pip3 install -r requirements.txt

# Run exploit (all platforms)
python3 remote_command_execution_vulnerability_v2.py
```

### Testing and Development

```powershell
# Start local TCP file server manually
python tcp_file_server.py script_tools

# Start local HTTP file server manually
python http_file_server.py build

# Test router connectivity
telnet <router_ip>
# Or with SSH (after exploit)
ssh -oKexAlgorithms=+diffie-hellman-group1-sha1 -c 3des-cbc root@<router_ip>
```

### Router Post-Exploitation Commands

Once connected to router:
```bash
# Create MTD backup
cd /tmp
./script.sh mtd_backup

# Remount filesystem as read-write
./script.sh remount

# Install OpenWRT (example for 4A Gigabit)
cd /tmp
curl <firmware_url> --output firmware.bin
./busybox sha256sum firmware.bin
mtd -e OS1 -r write firmware.bin OS1
```

## File Structure

- `script_tools/` - Contains static binaries (busybox, dropbear) for target routers
- `readme/` - Screenshots and GIFs demonstrating the exploit
- `build/` - Generated directory containing exploit payloads (created at runtime)
- `extras/` - Additional utilities and deprecated scripts

## Important Notes

- **Network Requirements**: Router needs internet access for v0.0.2+, script must run from same IP as admin login
- **Architecture Compatibility**: Different router models use different CPU architectures (mipsel vs mips)
- **Windows Limitations**: v1 has Windows compatibility issues, use Docker or v2 script
- **Router Mode Issues**: AP mode may cause problems, try WiFi Repeater or Gateway mode instead

## Security Considerations

- This tool exploits known CVEs in Xiaomi router firmware
- Only use on routers you own or have explicit permission to test
- Backup router firmware before attempting OpenWRT installation
- Some firmware versions are patched and no longer vulnerable

## Supported Firmware Versions

The exploit works on specific firmware versions for each router model. Check the main README.md for the complete compatibility matrix, as support varies by model and firmware version.