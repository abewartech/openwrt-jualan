#!/usr/bin/env python3
"""
ZeroTier Installation Script for OpenWrt
This script installs and configures ZeroTier on an OpenWrt router.
"""

import os
import sys
import time
import argparse
import subprocess
from contextlib import contextmanager

def remove_known_hosts_entry(host):
    """Remove the host from known_hosts file to prevent SSH key verification errors."""
    try:
        known_hosts_file = os.path.expanduser('~/.ssh/known_hosts')
        if os.path.exists(known_hosts_file):
            subprocess.run(['ssh-keygen', '-R', host], 
                          stdout=subprocess.PIPE, 
                          stderr=subprocess.PIPE)
            print(f"Removed {host} from known_hosts file")
    except Exception as e:
        print(f"Warning: Could not remove known_hosts entry: {e}")

@contextmanager
def ssh_connection(host, username):
    """Create an SSH connection using external SSH command."""
    # Test SSH connection first
    test_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {username}@{host} echo 'SSH connection successful'"
    print(f"Testing SSH connection: {test_cmd}")
    
    try:
        result = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"SSH connection failed: {result.stderr}")
            print("\nTroubleshooting tips:")
            print("1. Ensure the router is powered on and accessible at the specified IP address")
            print("2. Verify you can SSH to the router manually using the same credentials")
            print("3. Check if the router's SSH service is enabled and running")
            print("4. Try resetting the router's SSH service or rebooting the router")
            sys.exit(1)
        
        print("SSH connection successful. Using external SSH for commands.")
        
        # Create a simple client object to mimic paramiko's interface
        class ExternalSSHClient:
            def __init__(self, host, username):
                self.host = host
                self.username = username
            
            def exec_command(self, command, timeout=30):
                """Execute a command via SSH and return stdin, stdout, stderr."""
                ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 {self.username}@{self.host} {command}"
                print(f"Running external SSH: {ssh_cmd}")
                
                try:
                    result = subprocess.run(ssh_cmd, shell=True, capture_output=True, 
                                          text=True, timeout=timeout)
                    
                    # Create file-like objects to mimic paramiko's return values
                    class DummyFile:
                        def __init__(self, content=''):
                            self.content = content
                        def read(self):
                            return self.content
                        def readlines(self):
                            return self.content.splitlines()
                    
                    stdin = DummyFile()
                    stdout = DummyFile(result.stdout)
                    stderr = DummyFile(result.stderr)
                    
                    if result.stderr:
                        print(f"(stderr) {result.stderr}")
                    
                    return stdin, stdout, stderr
                except subprocess.TimeoutExpired:
                    print(f"Command failed: Command '{ssh_cmd}' timed out after {timeout} seconds. Retrying in 2s...")
                    time.sleep(2)
                    return self.exec_command(command, timeout)
                except Exception as e:
                    print(f"Error executing command: {e}")
                    return DummyFile(), DummyFile(), DummyFile(str(e))
            
            def close(self):
                """Close the SSH connection (no-op for external SSH)."""
                pass
        
        client = ExternalSSHClient(host, username)
        yield client
    except Exception as e:
        print(f"Error establishing SSH connection: {e}")
        sys.exit(1)

def run_command(client, command, retry=True, max_retries=3, retry_delay=2):
    """Run a command on the router and return stdout and stderr."""
    for attempt in range(max_retries if retry else 1):
        try:
            stdin, stdout, stderr = client.exec_command(command)
            out = stdout.read()
            err = stderr.read()
            return out, err
        except Exception as e:
            if attempt < max_retries - 1 and retry:
                print(f"Command failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"Command failed after {max_retries} attempts: {e}")
                return "", str(e)
    return "", "Max retries exceeded"

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Install and configure ZeroTier on OpenWrt')
    parser.add_argument('--network', default='56374ac9a4f632db', help='ZeroTier Network ID')
    args = parser.parse_args()
    
    network_id = args.network
    print(f"Using default ZeroTier Network ID: {network_id}")
    
    # Remove known hosts entry for the router
    remove_known_hosts_entry('192.168.1.1')
    
    # Connect to the router
    print("Connecting to 192.168.1.1 as root...")
    with ssh_connection('192.168.1.1', 'root') as client:
        # Step 1: Prepare OpenWrt for ZeroTier
        print("\n=== Preparing OpenWrt for ZeroTier ===")
        prepare_commands = [
            # Disable signature check for faster package installation
            "sed -i 's/^option \\?check_signature/# option check_signature/g' /etc/opkg.conf",
        ]
        
        for i, cmd in enumerate(prepare_commands, 1):
            print(f"[prep {i}/{len(prepare_commands)}] $ {cmd}")
            run_command(client, cmd)
        
        # Step 2: Install ZeroTier packages
        print("\n=== Installing ZeroTier packages ===")
        install_commands = [
            # Update package lists
            "opkg update",
            # Install ZeroTier
            "opkg install zerotier",
        ]
        
        for i, cmd in enumerate(install_commands, 1):
            print(f"[install {i}/{len(install_commands)}] $ {cmd}")
            run_command(client, cmd)
        
        # Step 3: Configure ZeroTier
        print("\n=== Configuring ZeroTier ===")
        config_commands = [
            # Create config directory if it doesn't exist
            "mkdir -p /etc/config",
            
            # Create basic ZeroTier config
            "cat > /etc/config/zerotier << 'EOT'\nconfig zerotier 'global'\n\toption enabled '1'\n\nconfig network 'mynet'\n\toption id '" + network_id + "'\nEOT",
            
            # Enable and restart ZeroTier service
            "/etc/init.d/zerotier enable",
            "/etc/init.d/zerotier restart",
            
            # Wait for service to start
            "sleep 5",
        ]
        
        for i, cmd in enumerate(config_commands, 1):
            print(f"[config {i}/{len(config_commands)}] $ {cmd}")
            run_command(client, cmd)
        
        # Step 4: Configure network and firewall
        print("\n=== Configuring network and firewall ===")
        net_fw_commands = [
            # Network configuration
            "uci set network.zerotier=interface",
            "uci set network.zerotier.proto='none'",
            "uci set network.zerotier.device='zt0'",
            "uci commit network",
            
            # Firewall configuration
            "uci add firewall zone",
            "uci set firewall.@zone[-1].name='zerotier'",
            "uci set firewall.@zone[-1].input='ACCEPT'",
            "uci set firewall.@zone[-1].output='ACCEPT'",
            "uci set firewall.@zone[-1].forward='ACCEPT'",
            "uci set firewall.@zone[-1].masq='1'",
            "uci add_list firewall.@zone[-1].network='zerotier'",
            
            # Forwarding rules
            "uci add firewall forwarding",
            "uci set firewall.@forwarding[-1].src='zerotier'",
            "uci set firewall.@forwarding[-1].dest='lan'",
            
            "uci add firewall forwarding",
            "uci set firewall.@forwarding[-1].src='lan'",
            "uci set firewall.@forwarding[-1].dest='zerotier'",
            
            "uci commit firewall",
            
            # Reload services
            "/etc/init.d/network restart",
            "/etc/init.d/firewall restart",
        ]
        
        for i, cmd in enumerate(net_fw_commands, 1):
            print(f"[network {i}/{len(net_fw_commands)}] $ {cmd}")
            run_command(client, cmd)
        
        # Step 5: Display ZeroTier status and information
        print("\n=== ZeroTier Status ===")
        run_command(client, "cat /var/lib/zerotier-one/identity.public || echo 'Identity file not found yet'")
        
        print("\n=== Installation Complete ===")
        print("ZeroTier has been installed and configured on your OpenWrt router.")
        print(f"Network ID: {network_id}")
        print("\nIMPORTANT: You need to authorize this device in your ZeroTier Central account:")
        print("1. Go to https://my.zerotier.com/")
        print("2. Select your network")
        print("3. Find this device in the members list and check 'Auth'")
        print("\nAfter authorization, your router will be connected to your ZeroTier network.")
        
        # Troubleshooting information
        print("\n=== Troubleshooting ===")
        print("If you encounter issues:")
        print("1. Check if ZeroTier is running: /etc/init.d/zerotier status")
        print("2. Restart ZeroTier: /etc/init.d/zerotier restart")
        print("3. Check logs: logread | grep zerotier")
        print("4. Verify network configuration: uci show network.zerotier")
        print("5. Verify firewall configuration: uci show firewall | grep zerotier")

if __name__ == "__main__":
    main()