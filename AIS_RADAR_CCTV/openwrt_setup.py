#!/usr/bin/env python3
"""
openwrt_setup.py

Script untuk mengeksekusi rangkaian perintah OpenWrt (Zerotier, AIS proxy, MQTT, firewall)
via SSH menggunakan paramiko.

Usage:
  python3 openwrt_setup.py --host 10.0.0.1 --user root --password root --netid 17d709436c2c81fc

Catatan:
  - Pastikan router reachable via SSH dan kredensial benar.
  - Script ini menjalankan banyak perintah berhak root.
  - Gunakan --dry-run untuk hanya menampilkan perintah.
"""

import paramiko
import argparse
import time
import socket
import sys
import os
from datetime import datetime

LOGFILE = "openwrt_setup.log"
RECV_CHUNK = 4096

def log(msg):
    s = f"{datetime.utcnow().isoformat()}Z  {msg}"
    print(s)
    with open(LOGFILE, "a") as f:
        f.write(s + "\n")

def connect_ssh(host, port, user, password, timeout=20):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    log(f"Connecting to {host}:{port} as {user} ...")
    client.connect(hostname=host, port=port, username=user, password=password, timeout=timeout)
    log("SSH connected")
    return client

def run_cmd(client, cmd, timeout=30, wait_for_stdout=True):
    """
    Run a command via SSH and return (exit_status, stdout, stderr)
    This will attempt to read stdout/stderr until channel is closed or timeout expires.
    """
    log(f"RUN: {cmd}")
    transport = client.get_transport()
    channel = transport.open_session()
    channel.exec_command(cmd)
    stdout = b""
    stderr = b""
    start = time.time()
    # Keep reading until channel.closed and no more data, or timeout
    while True:
        if channel.recv_ready():
            data = channel.recv(RECV_CHUNK)
            stdout += data
        if channel.recv_stderr_ready():
            data = channel.recv_stderr(RECV_CHUNK)
            stderr += data
        if channel.exit_status_ready():
            break
        if (time.time() - start) > timeout:
            # Timeout: try to collect what's left and return
            log(f"Command timeout after {timeout}s")
            # do not forcibly close channel: try to read any last data
            time.sleep(0.2)
            break
        time.sleep(0.1)
    exit_status = None
    try:
        exit_status = channel.recv_exit_status()
    except Exception:
        exit_status = -1
    stdout_text = stdout.decode(errors="ignore")
    stderr_text = stderr.decode(errors="ignore")
    if stdout_text:
        log(f"STDOUT: {stdout_text.strip()}")
    if stderr_text:
        log(f"STDERR: {stderr_text.strip()}")
    log(f"Exit: {exit_status}")
    return exit_status, stdout_text, stderr_text

def run_cmd_simple(client, cmd, timeout=10):
    """Helper wrapper"""
    return run_cmd(client, cmd, timeout=timeout)

def write_remote_file(client, remote_path, content):
    """Write file to remote path using cat <<'EOF' > remote_path pattern"""
    # Escape single quotes in EOF delimiter usage is avoided by using <<'EOF'
    cmd = f"cat <<'EOF' > {remote_path}\n{content}\nEOF\n"
    return run_cmd(client, cmd, timeout=30)

def ensure_dir(client, path, mode="700"):
    run_cmd_simple(client, f"mkdir -p {path}")
    run_cmd_simple(client, f"chmod {mode} {path}")

def enable_service_with_fallback(client, service_name, start_priority="99"):
    """
    Try to run '/etc/init.d/<service> enable'. If it seems to hang or returns non-zero,
    create symlink in /etc/rc.d manually as fallback.
    """
    enable_cmd = f"/etc/init.d/{service_name} enable"
    # try with short timeout
    status, out, err = run_cmd(client, enable_cmd, timeout=8)
    if status == 0:
        log(f"{service_name} enabled via init script")
        return True
    else:
        # fallback: create symlink
        symlink = f"/etc/rc.d/S{start_priority}{service_name}"
        log(f"FALLBACK: creating symlink {symlink} -> /etc/init.d/{service_name}")
        run_cmd_simple(client, f"ln -sf /etc/init.d/{service_name} {symlink}")
        # verify
        status2, out2, err2 = run_cmd_simple(client, f"ls -l {symlink}")
        return True

def main():
    parser = argparse.ArgumentParser(description="OpenWrt SSH setup script")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", default=22, type=int)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", required=True)
    parser.add_argument("--netid", default="17d709436c2c81fc", help="Zerotier network ID")
    parser.add_argument("--broker", default="mqtt.cakrawala.id", help="MQTT broker host")
    parser.add_argument("--camera_ip", default="10.0.0.64", help="IP camera internal")
    parser.add_argument("--ais_src_ip", default="10.0.0.156", help="AIS source IP")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    if args.dry_run:
        log("DRY RUN - commands will be printed but not executed")

    # Basic list of commands run in sequence:
    commands = []

    # 1) Preparasi opkg feeds (with caution)
    commands.append("sed -i 's/option check_signature/# option check_signature/g' /etc/opkg.conf || true")
    commands.append("ARCH=$(awk -F= '/OPENWRT_ARCH/ {print $2}' /etc/os-release 2>/dev/null | tr -d '\"' || echo '')")
    commands.append("echo \"src/gz custom_generic https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/generic\" >> /etc/opkg/customfeeds.conf || true")
    commands.append("echo \"src/gz custom_arch https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/${ARCH}\" >> /etc/opkg/customfeeds.conf || true")
    commands.append("opkg update || true")

    # 2) Install Zerotier packages (try safe sequence)
    commands += [
        "opkg update || true",
        "opkg install zerotier luci-app-zerotier luci-compat || true"
    ]

    # Backups
    commands.append("cp -a /etc/config/zerotier /tmp/zerotier.config.backup 2>/dev/null || true")
    commands.append("cp -a /etc/init.d/zerotier /tmp/zerotier.init.backup 2>/dev/null || true")

    # If conflict earlier, suggested flow: remove zerotier then install luci-app-zerotier which pulls dep
    commands.append("opkg remove zerotier || true")
    commands.append("opkg update || true")
    commands.append("opkg install luci-app-zerotier || true")

    # enable/start zerotier (we will call enable fallback helper too)
    commands.append("/etc/init.d/zerotier start || true")

    # join network & check
    commands.append(f"zerotier-cli join {args.netid} || true")
    commands.append("sleep 2 || true")
    commands.append("zerotier-cli status || true")
    commands.append("zerotier-cli listnetworks || true")

    # 3) Paket dasar
    commands += [
        "opkg update || true",
        "opkg install socat netcat mosquitto-client mosquitto-client-ssl lua-mosquitto || true"
    ]

    # 4) Create aisproxy init script (fixed and robust)
    aisproxy_content = f"""#!/bin/sh /etc/rc.common
# AIS TCP proxy: dengarkan port LAN:2003, forward ke {args.ais_src_ip}:2001
START=95
STOP=10

start() {{
    echo "Starting AIS proxy (socat) ..."
    procd_open_instance
    procd_set_param command /usr/bin/socat TCP-LISTEN:2003,fork TCP:{args.ais_src_ip}:2001
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_set_param respawn
    procd_close_instance
}}

stop() {{
    procd_killall socat 15 || true
}}
"""
    # 5) Firewall (UCI) rules
    firewall_cmds = [
        # RTSP 554 -> camera
        "uci add firewall redirect",
        f"uci set firewall.@redirect[-1].name='RTSP_554'",
        "uci set firewall.@redirect[-1].src='wan'",
        "uci set firewall.@redirect[-1].src_dport='554'",
        "uci set firewall.@redirect[-1].dest='lan'",
        f"uci set firewall.@redirect[-1].dest_ip='{args.camera_ip}'",
        "uci set firewall.@redirect[-1].dest_port='554'",
        "uci set firewall.@redirect[-1].proto='tcp'",
        "uci commit firewall",
        "/etc/init.d/firewall restart",

        # HTTP web port mapping example
        "uci add firewall redirect",
        "uci set firewall.@redirect[-1].name='CAM_HTTP_80'",
        "uci set firewall.@redirect[-1].src='wan'",
        "uci set firewall.@redirect[-1].src_dport='8378'",
        "uci set firewall.@redirect[-1].dest='lan'",
        f"uci set firewall.@redirect[-1].dest_ip='{args.camera_ip}'",
        "uci set firewall.@redirect[-1].dest_port='80'",
        "uci set firewall.@redirect[-1].proto='tcp'",
        "uci commit firewall",
        "/etc/init.d/firewall restart",

        # AIS proxy port
        "uci add firewall redirect",
        "uci set firewall.@redirect[-1].name='AIS_PROXY'",
        "uci set firewall.@redirect[-1].src='wan'",
        "uci set firewall.@redirect[-1].src_dport='8379'",
        "uci set firewall.@redirect[-1].dest='lan'",
        f"uci set firewall.@redirect[-1].dest_ip='{args.ais_src_ip}'",
        "uci set firewall.@redirect[-1].dest_port='2001'",
        "uci set firewall.@redirect[-1].proto='tcp'",
        "uci commit firewall",
        "/etc/init.d/firewall restart",
    ]

    # 6) aismqtt script content (robust)
    aismqtt_sh = f"""#!/bin/sh
BROKER="{args.broker}"
TOPIC="ais/raw"
SRC_HOST="{args.ais_src_ip}"
SRC_PORT=2001

while true; do
  echo "Connecting to $SRC_HOST:$SRC_PORT ..."
  if nc -w 10 $SRC_HOST $SRC_PORT | while IFS= read -r line; do
    [ -z "$line" ] && continue
    echo "$line" | mosquitto_pub -h "$BROKER" -t "$TOPIC" -s
  done; then
    echo "Connection closed cleanly. Reconnect after 2s."
    sleep 2
  else
    echo "Connection failed. Retry in 5s."
    sleep 5
  fi
done
"""

    aismqtt_init = """#!/bin/sh /etc/rc.common
START=96
STOP=10

start() {
    procd_open_instance
    procd_set_param command /bin/sh /root/aismqtt.sh
    procd_set_param respawn
    procd_close_instance
}

stop() {
    procd_killall sh 15 || true
}
"""

    # Establish SSH and run
    client = None
    try:
        if not args.dry_run:
            client = connect_ssh(args.host, args.port, args.user, args.password)
        else:
            log("DRY RUN: Not connecting via SSH")

        # Execute prepared commands
        for cmd in commands:
            if args.dry_run:
                log(f"[DRY RUN] {cmd}")
            else:
                # run command but tolerant of hangs for enable fallback
                # Special-case the 'enable' step is handled separately below
                run_cmd_simple(client, cmd,)

        # Try enabling zerotier (use helper fallback)
        if not args.dry_run:
            enable_service_with_fallback(client, "zerotier", start_priority="99")
            # start service just in case
            run_cmd_simple(client, "/etc/init.d/zerotier start || true")
            time.sleep(2)
            run_cmd_simple(client, f"zerotier-cli join {args.netid} || true")
            run_cmd_simple(client, "zerotier-cli status || true")
            run_cmd_simple(client, "zerotier-cli listnetworks || true")

        # Install packages (already attempted above) - ensure socat etc exist
        if not args.dry_run:
            run_cmd_simple(client, "opkg update || true")
            run_cmd_simple(client, "opkg install socat netcat mosquitto-client mosquitto-client-ssl lua-mosquitto || true")

        # Create aisproxy init script
        if args.dry_run:
            log("[DRY RUN] will write /etc/init.d/aisproxy with corrected content")
        else:
            write_remote_file(client, "/etc/init.d/aisproxy", aisproxy_content)
            run_cmd_simple(client, "chmod +x /etc/init.d/aisproxy || true")
            enable_service_with_fallback(client, "aisproxy", start_priority="95")
            run_cmd_simple(client, "/etc/init.d/aisproxy start || true")
            run_cmd_simple(client, "logread | tail -n 20 || true")

        # Deploy aismqtt.sh and init
        if args.dry_run:
            log("[DRY RUN] will write /root/aismqtt.sh and /etc/init.d/aismqtt")
        else:
            write_remote_file(client, "/root/aismqtt.sh", aismqtt_sh)
            run_cmd_simple(client, "chmod +x /root/aismqtt.sh || true")
            write_remote_file(client, "/etc/init.d/aismqtt", aismqtt_init)
            run_cmd_simple(client, "chmod +x /etc/init.d/aismqtt || true")
            enable_service_with_fallback(client, "aismqtt", start_priority="96")
            run_cmd_simple(client, "/etc/init.d/aismqtt start || true")
            run_cmd_simple(client, "ps w | grep aismqtt || true")

        # Apply firewall UCI rules
        for fc in firewall_cmds:
            if args.dry_run:
                log(f"[DRY RUN] {fc}")
            else:
                run_cmd_simple(client, fc)

        log("All commands submitted. Check router logs and services for live status.")
        log(f"Local log saved to {LOGFILE}")
    except (paramiko.ssh_exception.SSHException, socket.error) as e:
        log(f"SSH error: {e}")
        sys.exit(2)
    finally:
        if client:
            client.close()
            log("SSH connection closed")

if __name__ == "__main__":
    main()
