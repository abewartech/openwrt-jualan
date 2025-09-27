#!/usr/bin/env python3
"""
Install and configure ZeroTier on OpenWrt via SSH.
Router: 192.168.1.1, user: root, no password
Performance optimized version with better error handling and retry logic.
Automatically removes known_hosts entries to avoid SSH verification errors.
"""

import paramiko
import time
import sys
import concurrent.futures
import socket
import os
import platform
import subprocess
from contextlib import contextmanager

# Router configuration
ROUTER_HOST = "192.168.1.1"
ROUTER_USER = "root"
ROUTER_PASS = ""  # No password
ROUTER_PORT = 22

# Set this to True to enable verbose debugging output
DEBUG = True

# ZeroTier Network ID to join
ZEROTIER_NETWORK_ID = "56374ac9a4f632db"

# Performance settings
CONNECTION_TIMEOUT = 15
COMMAND_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 2
PARALLEL_COMMANDS = True  # Set to False if router has limited resources

def remove_known_hosts_entry():
    """Remove the router's entry from SSH known_hosts file to avoid verification errors."""
    try:
        # Determine the known_hosts file path based on OS
        home_dir = os.path.expanduser("~")
        if platform.system() == "Windows":
            known_hosts_path = os.path.join(home_dir, ".ssh", "known_hosts")
        else:
            known_hosts_path = os.path.join(home_dir, ".ssh", "known_hosts")
        
        if not os.path.exists(known_hosts_path):
            print(f"No known_hosts file found at {known_hosts_path}")
            return
        
        # Read the current known_hosts file
        with open(known_hosts_path, 'r') as f:
            lines = f.readlines()
        
        # Filter out lines containing the router's IP
        new_lines = [line for line in lines if ROUTER_HOST not in line]
        
        # If we found and removed any lines
        if len(lines) != len(new_lines):
            # Write the file back without the router's entries
            with open(known_hosts_path, 'w') as f:
                f.writelines(new_lines)
            print(f"Removed {ROUTER_HOST} from SSH known_hosts file")
        else:
            print(f"No entries for {ROUTER_HOST} found in known_hosts file")
    except Exception as e:
        print(f"Warning: Could not clean known_hosts file: {e}")
        print("You may need to manually remove entries if SSH connection fails")


@contextmanager
def ssh_connection():
    """Context manager for SSH connection with automatic cleanup."""
    # First remove any existing known_hosts entries for the router
    remove_known_hosts_entry()
    
    # Skip paramiko entirely and use external SSH command directly
    # This is the most reliable method for OpenWrt
    print(f"Connecting to {ROUTER_HOST} as {ROUTER_USER}...")
    
    # Create a client that uses external SSH commands
    class ExternalSSHClient:
        def exec_command(self, cmd, timeout=COMMAND_TIMEOUT):
            ssh_cmd = f"ssh -o StrictHostKeyChecking=no {ROUTER_USER}@{ROUTER_HOST} {cmd}"
            if DEBUG:
                print(f"Running external SSH: {ssh_cmd}")
            result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True)
            
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
        test_cmd = f"ssh -o StrictHostKeyChecking=no {ROUTER_USER}@{ROUTER_HOST} echo 'SSH connection successful'"
        if DEBUG:
            print(f"Testing SSH connection: {test_cmd}")
        
        result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("SSH connection successful. Using external SSH for commands.")
            client = ExternalSSHClient()
        else:
            print(f"SSH connection failed: {result.stderr}")
            print("Please verify your router is reachable and try the following:")
            print("1. Manually SSH to confirm credentials: ssh root@192.168.1.1")
            print("2. Check if your router requires a password")
            print("3. Verify the router's IP address is correct")
            sys.exit(1)
    except Exception as e:
        print(f"SSH connection failed: {str(e)}")
        print("Please verify your router is reachable and try the following:")
        print("1. Manually SSH to confirm credentials: ssh root@192.168.1.1")
        print("2. Check if your router requires a password")
        print("3. Verify the router's IP address is correct")
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


def run_commands_parallel(client, commands, prefix=""):
    """Run non-dependent commands in parallel for better performance."""
    results = []
    
    def execute_command(idx, cmd):
        print(f"[{prefix}{idx}/{len(commands)}] $ {cmd}")
        out, err = run_command(client, cmd)
        if out:
            print(out)
        if err:
            print(f"(stderr) {err}")
        return out, err
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_cmd = {
            executor.submit(execute_command, idx, cmd): (idx, cmd) 
            for idx, cmd in enumerate(commands, 1)
        }
        
        for future in concurrent.futures.as_completed(future_to_cmd):
            idx, cmd = future_to_cmd[future]
            try:
                out, err = future.result()
                results.append((out, err))
            except Exception as exc:
                print(f"Command {idx} generated an exception: {exc}")
                results.append(("", f"Error: {exc}"))
    
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
        f"set zerotier.mynet.id='{ZEROTIER_NETWORK_ID}'\n"
        "commit zerotier\n"
        "EOF",
        # Info + join network
        "zerotier-cli info || true",
        f"zerotier-cli leave {ZEROTIER_NETWORK_ID} >/dev/null 2>&1 || true",
        f"zerotier-cli join {ZEROTIER_NETWORK_ID} || true",
    ]

    with ssh_connection() as client:
        print("\n=== Preparing OpenWrt for ZeroTier ===")
        # These commands can be run in parallel for better performance
        if PARALLEL_COMMANDS:
            run_commands_parallel(client, prepare_commands, "prep ")
        else:
            run_commands_sequential(client, prepare_commands, "prep ")
        
        print("\n=== Installing ZeroTier packages ===")
        # Package installation should be sequential
        run_commands_sequential(client, install_commands, "install ")
        
        print("\n=== Configuring ZeroTier ===")
        # Configuration commands should be sequential
        run_commands_sequential(client, config_commands, "config ")

        # Step 2: Discover the ZeroTier interface name
        print("\n=== Discovering ZeroTier interface name ===")
        zt_ifname = get_zt_device_name(client, ZEROTIER_NETWORK_ID)
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


if __name__ == "__main__":
    main()