#!/usr/bin/env python3
"""
Install and configure ZeroTier on OpenWrt via SSH.
This script uses external SSH commands instead of Paramiko for improved compatibility.
Automatically configures ZeroTier, network settings, and firewall rules.

Usage:
    python install_zerotier_fix_optimized.py [network_id]

If network_id is not provided, the default network ID will be used.
"""

import subprocess
import sys
import os
import time
import socket
import platform
from contextlib import contextmanager

# Router configuration - Customize these settings
ROUTER_HOST = "192.168.1.1"  # Default OpenWrt IP address
ROUTER_USER = "root"         # Default OpenWrt username
ROUTER_PORT = 22             # Default SSH port

# ZeroTier Network ID to join - Replace with your network ID or pass as argument
DEFAULT_ZEROTIER_NETWORK_ID = "56374ac9a4f632db"

# Performance settings
CONNECTION_TIMEOUT = 15
COMMAND_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2

# Set to True for verbose output
DEBUG = True

def remove_known_hosts_entry():
    """Remove the router's entry from SSH known_hosts to prevent verification errors."""
    known_hosts_file = None
    
    # Determine the location of the known_hosts file based on the OS
    if platform.system() == "Windows":
        known_hosts_file = os.path.expanduser("~/.ssh/known_hosts")
    else:  # Linux, macOS, etc.
        known_hosts_file = os.path.expanduser("~/.ssh/known_hosts")
    
    if not os.path.exists(known_hosts_file):
        if DEBUG:
            print(f"Known hosts file not found at {known_hosts_file}")
        return
    
    try:
        # Use ssh-keygen to remove the host entry
        if platform.system() == "Windows":
            # On Windows, we'll use a different approach since ssh-keygen might not be available
            with open(known_hosts_file, 'r') as f:
                lines = f.readlines()
            
            with open(known_hosts_file, 'w') as f:
                for line in lines:
                    if ROUTER_HOST not in line:
                        f.write(line)
            
            if DEBUG:
                print(f"Removed {ROUTER_HOST} from known_hosts file")
        else:
            # On Unix-like systems, use ssh-keygen
            subprocess.run(["ssh-keygen", "-R", ROUTER_HOST], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            
            if DEBUG:
                print(f"Removed {ROUTER_HOST} from known_hosts file using ssh-keygen")
    except Exception as e:
        print(f"Warning: Failed to remove known hosts entry: {e}")


@contextmanager
def ssh_connection():
    """Context manager for SSH connection with automatic cleanup."""
    # First remove any existing known_hosts entries for the router
    remove_known_hosts_entry()
    
    print(f"Connecting to {ROUTER_HOST} as {ROUTER_USER}...")
    
    # Create a client that uses external SSH commands
    class ExternalSSHClient:
        def exec_command(self, cmd, timeout=COMMAND_TIMEOUT):
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout={CONNECTION_TIMEOUT} {ROUTER_USER}@{ROUTER_HOST} {cmd}"
            if DEBUG:
                print(f"Running external SSH: {ssh_cmd}")
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            
            # Create file-like objects for stdout and stderr
            class DummyFile:
                def __init__(self, content):
                    self.content = content
                def read(self):
                    return self.content.encode('utf-8')
            
            stdin = None
            stdout = DummyFile(result.stdout)
            stderr = DummyFile(result.stderr)
            return stdin, stdout, stderr
        
        def close(self):
            pass  # Nothing to close for external SSH

    # Test if SSH works
    try:
        test_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout={CONNECTION_TIMEOUT} {ROUTER_USER}@{ROUTER_HOST} echo 'SSH connection successful'"
        if DEBUG:
            print(f"Testing SSH connection: {test_cmd}")
        
        result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True, timeout=CONNECTION_TIMEOUT)
        
        if result.returncode == 0:
            print("SSH connection successful. Using external SSH for commands.")
            client = ExternalSSHClient()
        else:
            print(f"SSH connection failed: {result.stderr}")
            print("\nPlease verify your router is reachable and try the following:")
            print(f"1. Manually SSH to confirm credentials: ssh {ROUTER_USER}@{ROUTER_HOST}")
            print("2. Check if your router requires a password")
            print("3. Verify the router's IP address is correct")
            print("4. Ensure SSH service is running on your router")
            sys.exit(1)
    except Exception as e:
        print(f"SSH connection failed: {str(e)}")
        print("\nPlease verify your router is reachable and try the following:")
        print(f"1. Manually SSH to confirm credentials: ssh {ROUTER_USER}@{ROUTER_HOST}")
        print("2. Check if your router requires a password")
        print("3. Verify the router's IP address is correct")
        print("4. Ensure SSH service is running on your router")
        sys.exit(1)
    
    try:
        yield client
    finally:
        if 'client' in locals():
            client.close()


def run_command(client, cmd, retry=True):
    """Run a single SSH command with retry logic."""
    for attempt in range(MAX_RETRIES if retry else 1):
        try:
            stdin, stdout, stderr = client.exec_command(cmd, timeout=COMMAND_TIMEOUT)
            out = stdout.read().decode("utf-8", errors="ignore").strip()
            err = stderr.read().decode("utf-8", errors="ignore").strip()
            
            return out, err
        except Exception as e:
            if attempt < MAX_RETRIES - 1 and retry:
                print(f"Command failed: {e}. Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                print(f"Command failed after {attempt+1} attempts: {e}")
                return "", f"Error: {e}"


def run_commands_sequential(client, commands, prefix=""):
    """Run commands sequentially with progress indicators."""
    results = []
    for idx, cmd in enumerate(commands, 1):
        print(f"[{prefix}{idx}/{len(commands)}] $ {cmd}")
        out, err = run_command(client, cmd)
        
        if out:
            print(out)
        if err:
            print(f"(stderr) {err}")
        
        results.append((out, err))
        # Small delay between commands to avoid overwhelming the router
        time.sleep(0.5)
    
    return results


def get_zt_device_name(client, network_id, retries=10, delay=2):
    """Query ZeroTier portDeviceName with retries until it appears."""
    cmd = f"zerotier-cli get {network_id} portDeviceName"
    for attempt in range(1, retries + 1):
        out, err = run_command(client, cmd, retry=False)
        if out and out != 'unknown':
            return out
        
        print(f"Waiting for ZeroTier interface... attempt {attempt}/{retries}")
        if err:
            print(f"(stderr) {err}")
        
        time.sleep(delay)
    
    return ""


def main():
    # Get ZeroTier Network ID from command line argument or use default
    zerotier_network_id = DEFAULT_ZEROTIER_NETWORK_ID
    if len(sys.argv) > 1:
        zerotier_network_id = sys.argv[1]
        print(f"Using provided ZeroTier Network ID: {zerotier_network_id}")
    else:
        print(f"Using default ZeroTier Network ID: {zerotier_network_id}")
        if zerotier_network_id == "your_network_id_here":
            print("WARNING: You are using the placeholder network ID. Please replace it with your actual ZeroTier network ID.")
            print("You can specify your network ID as a command line argument: python install_zerotier_fix_optimized.py YOUR_NETWORK_ID")
            response = input("Do you want to continue with the placeholder network ID? (y/n): ")
            if response.lower() != 'y':
                print("Installation aborted. Please run the script again with your actual ZeroTier network ID.")
                sys.exit(0)

    # Step 1: Prepare opkg feeds and install packages
    prepare_commands = [
        # Disable signature check for faster package installation
        "sed -i 's/^option \\?check_signature/# option check_signature/g' /etc/opkg.conf",
        # Ensure customfeeds file exists and append (skip duplicates)
        "mkdir -p /etc/opkg",
        "grep -q 'custom_generic' /etc/opkg/customfeeds.conf 2>/dev/null || echo 'src/gz custom_generic https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/generic' >> /etc/opkg/customfeeds.conf",
        "ARCH=$( . /etc/os-release; echo $OPENWRT_ARCH ); grep -q custom_arch /etc/opkg/customfeeds.conf 2>/dev/null || echo src/gz custom_arch https://raw.githubusercontent.com/lrdrdn/my-opkg-repo/main/$ARCH >> /etc/opkg/customfeeds.conf",
    ]
    
    # Update and install packages (these should be run sequentially)
    install_commands = [
        # Update package lists
        "opkg update",
        # Install packages with --force-depends for faster installation
        "opkg install --force-depends luci-compat || true",
        "opkg install --force-depends zerotier || true",
        "opkg install --force-depends zerotier-utils || true",
        "opkg install --force-depends luci-app-zerotier || true",
    ]
    
    # Service and configuration commands
    config_commands = [
        # Enable and start service
        "/etc/init.d/zerotier enable || true",
        "/etc/init.d/zerotier start || true",
        # UCI zerotier base config (combine multiple UCI commands for better performance)
        "uci batch <<EOF\n"
        "set zerotier.global.enabled='1'\n"
        "delete zerotier.earth\n"
        "set zerotier.mynet=network\n"
        f"set zerotier.mynet.id='{zerotier_network_id}'\n"
        "commit zerotier\n"
        "EOF",
        # Info + join network
        "zerotier-cli info || true",
        f"zerotier-cli leave {zerotier_network_id} >/dev/null 2>&1 || true",
        f"zerotier-cli join {zerotier_network_id} || true",
    ]

    with ssh_connection() as client:
        print("\n=== Preparing OpenWrt for ZeroTier ===")
        run_commands_sequential(client, prepare_commands, "prep ")
        
        print("\n=== Installing ZeroTier packages ===")
        # Package installation should be sequential
        run_commands_sequential(client, install_commands, "install ")
        
        print("\n=== Configuring ZeroTier ===")
        # Configuration commands should be sequential
        run_commands_sequential(client, config_commands, "config ")

        # Step 2: Discover the ZeroTier interface name
        print("\n=== Discovering ZeroTier interface name ===")
        zt_ifname = get_zt_device_name(client, zerotier_network_id)
        if not zt_ifname:
            print("Failed to discover ZeroTier interface device name. Using fallback name.")
            zt_ifname = "ztnet0"  # fallback placeholder
        else:
            print(f"ZeroTier interface: {zt_ifname}")

        # Step 3: Configure OpenWrt network and firewall
        print("\n=== Configuring network and firewall ===")
        # Use UCI batch commands for better performance
        net_fw_commands = [
            # Network and firewall configuration in a single batch command
            f"uci batch <<EOF\n"
            "delete network.ZeroTier\n"
            "set network.ZeroTier=interface\n"
            "set network.ZeroTier.proto='none'\n"
            f"set network.ZeroTier.device='{zt_ifname}'\n"
            "add firewall zone\n"
            "set firewall.@zone[-1].name='vpn'\n"
            "set firewall.@zone[-1].input='ACCEPT'\n"
            "set firewall.@zone[-1].output='ACCEPT'\n"
            "set firewall.@zone[-1].forward='ACCEPT'\n"
            "set firewall.@zone[-1].masq='1'\n"
            "add_list firewall.@zone[-1].network='ZeroTier'\n"
            "add firewall forwarding\n"
            "set firewall.@forwarding[-1].src='vpn'\n"
            "set firewall.@forwarding[-1].dest='lan'\n"
            "add firewall forwarding\n"
            "set firewall.@forwarding[-1].src='vpn'\n"
            "set firewall.@forwarding[-1].dest='wan'\n"
            "add firewall forwarding\n"
            "set firewall.@forwarding[-1].src='lan'\n"
            "set firewall.@forwarding[-1].dest='vpn'\n"
            "commit\n"
            "EOF",
            # Reload services
            "/etc/init.d/network reload || true",
            "/etc/init.d/firewall reload || true",
        ]

        run_commands_sequential(client, net_fw_commands, "netfw ")

        print("\n=== ZeroTier installation completed ===")
        print("Rebooting router to apply all changes...")
        
        # Reboot router
        out, err = run_command(client, "reboot")
        print("Router is rebooting. ZeroTier setup complete.")
        print("\nAfter the router reboots:")
        print("1. Log into your ZeroTier account at https://my.zerotier.com/")
        print("2. Authorize your router in the network members section")
        print("3. Your router should now be connected to your ZeroTier network")


if __name__ == "__main__":
    main()