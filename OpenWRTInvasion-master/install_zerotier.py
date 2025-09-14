#!/usr/bin/env python3
"""
Install and configure ZeroTier on OpenWrt via SSH.
Router: 192.168.2.1, user: root, pass: @appDEV1234!!!!
"""

import paramiko
import time
import sys

ROUTER_HOST = "192.168.2.1"
ROUTER_USER = "root"
ROUTER_PASS = "@appDEV1234!!!!"
ROUTER_PORT = 22

# ZeroTier Network ID to join
ZEROTIER_NETWORK_ID = "56374ac9a4f632db"


def run_ssh_commands(commands):
    client = None
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f"Connecting to {ROUTER_HOST} as {ROUTER_USER}...")
        client.connect(ROUTER_HOST, port=ROUTER_PORT, username=ROUTER_USER, password=ROUTER_PASS, timeout=30)
        print("Connected. Executing commands...\n")

        for idx, cmd in enumerate(commands, 1):
            print(f"[{idx}/{len(commands)}] $ {cmd}")
            stdin, stdout, stderr = client.exec_command(cmd)
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            if out.strip():
                print(out.strip())
            if err.strip():
                print("(stderr)")
                print(err.strip())
            # Small delay between commands
            time.sleep(1.0)

        return client
    except paramiko.AuthenticationException:
        print("Authentication failed. Check credentials.")
        sys.exit(1)
    except Exception as exc:
        print(f"SSH error: {exc}")
        sys.exit(1)


def get_zt_device_name(client, network_id, retries=10, delay=3):
    """Query ZeroTier portDeviceName with retries until it appears."""
    cmd = f"zerotier-cli get {network_id} portDeviceName"
    for attempt in range(1, retries + 1):
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        if out and out != 'unknown':
            return out
        print(f"Waiting for ZeroTier interface... attempt {attempt}/{retries}")
        if err:
            print(f"(stderr) {err}")
        time.sleep(delay)
    return ""


def main():
    # Step 1: Prepare opkg feeds and install packages
    commands = [
        # Disable signature check
        "sed -i 's/^option \\?check_signature/# option check_signature/g' /etc/opkg.conf",
        # Ensure customfeeds file exists and append (skip duplicates)
        "mkdir -p /etc/opkg",
        "grep -q 'custom_generic' /etc/opkg/customfeeds.conf 2>/dev/null || echo 'src/gz custom_generic https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/generic' >> /etc/opkg/customfeeds.conf",
        "ARCH=$( . /etc/os-release; echo $OPENWRT_ARCH ); grep -q custom_arch /etc/opkg/customfeeds.conf 2>/dev/null || echo src/gz custom_arch https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/$ARCH >> /etc/opkg/customfeeds.conf",
        # Update
        "opkg update",
        # Base requirements and ZeroTier
        "opkg install luci-compat || true",
        "opkg install zerotier || true",
        "opkg install zerotier-utils || true",
        "opkg install luci-app-zerotier || true",
        # Enable and start service early
        "/etc/init.d/zerotier enable || true",
        "/etc/init.d/zerotier start || true",
        # UCI zerotier base config
        "uci set zerotier.global.enabled='1'",
        "uci -q delete zerotier.earth",
        "uci set zerotier.mynet=network",
        f"uci set zerotier.mynet.id='{ZEROTIER_NETWORK_ID}'",
        "uci commit zerotier",
        # Info + join network
        "zerotier-cli info || true",
        f"zerotier-cli leave {ZEROTIER_NETWORK_ID} >/dev/null 2>&1 || true",
        f"zerotier-cli join {ZEROTIER_NETWORK_ID} || true",
    ]

    client = run_ssh_commands(commands)

    # Step 2: Discover the ZeroTier interface name
    print("\nDiscovering ZeroTier interface name...")
    zt_ifname = get_zt_device_name(client, ZEROTIER_NETWORK_ID)
    if not zt_ifname:
        print("Failed to discover ZeroTier interface device name. You may need to run network/firewall steps manually later.")
        zt_ifname = "ztnet0"  # fallback placeholder
    else:
        print(f"ZeroTier interface: {zt_ifname}")

    # Step 3: Configure OpenWrt network and firewall
    net_fw_commands = [
        # Network interface
        "uci -q delete network.ZeroTier",
        "uci set network.ZeroTier=interface",
        "uci set network.ZeroTier.proto='none'",
        f"uci set network.ZeroTier.device='{zt_ifname}'",
        # Firewall zone and forwardings (create a new 'vpn' zone)
        "uci add firewall zone",
        "uci set firewall.@zone[-1].name='vpn'",
        "uci set firewall.@zone[-1].input='ACCEPT'",
        "uci set firewall.@zone[-1].output='ACCEPT'",
        "uci set firewall.@zone[-1].forward='ACCEPT'",
        "uci set firewall.@zone[-1].masq='1'",
        "uci add_list firewall.@zone[-1].network='ZeroTier'",
        # Forwardings between vpn<->lan/wan
        "uci add firewall forwarding",
        "uci set firewall.@forwarding[-1].src='vpn'",
        "uci set firewall.@forwarding[-1].dest='lan'",
        "uci add firewall forwarding",
        "uci set firewall.@forwarding[-1].src='vpn'",
        "uci set firewall.@forwarding[-1].dest='wan'",
        "uci add firewall forwarding",
        "uci set firewall.@forwarding[-1].src='lan'",
        "uci set firewall.@forwarding[-1].dest='vpn'",
        # Commit and apply
        "uci commit",
        "/etc/init.d/network reload || true",
        "/etc/init.d/firewall reload || true",
    ]

    for idx, cmd in enumerate(net_fw_commands, 1):
        print(f"[net/fw {idx}/{len(net_fw_commands)}] $ {cmd}")
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", errors="ignore").strip()
        err = stderr.read().decode("utf-8", errors="ignore").strip()
        if out:
            print(out)
        if err:
            print("(stderr)")
            print(err)
        time.sleep(0.8)

    print("\nZeroTier installation and configuration steps completed. Rebooting router...")
    stdin, stdout, stderr = client.exec_command("reboot")
    # Close after sending reboot
    time.sleep(1)
    client.close()
    print("Done. The router is rebooting.")


if __name__ == "__main__":
    main()
