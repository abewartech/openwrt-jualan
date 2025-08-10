#!/usr/bin/env python3
"""
SSH Router Setup Script
Connects to OpenWrt router via SSH and installs luci-app-mwan3
"""

import paramiko
import time
import sys

def ssh_connect_and_run_commands():
    # SSH connection parameters
    hostname = "192.168.2.1"
    username = "root"
    password = "@appDEV1234!!!!"
    port = 22
    
    # Commands to run
    commands = [
        "opkg update",
        "opkg install luci-app-mwan3"
    ]
    
    try:
        # Create SSH client
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        print(f"Connecting to {hostname} as {username}...")
        
        # Connect to the router
        ssh_client.connect(
            hostname=hostname,
            username=username,
            password=password,
            port=port,
            timeout=30
        )
        
        print("Successfully connected to the router!")
        
        # Execute commands
        for i, command in enumerate(commands, 1):
            print(f"\n[{i}/{len(commands)}] Executing: {command}")
            print("-" * 50)
            
            stdin, stdout, stderr = ssh_client.exec_command(command)
            
            # Get output
            output = stdout.read().decode('utf-8')
            error = stderr.read().decode('utf-8')
            
            # Print output
            if output:
                print("Output:")
                print(output)
            
            if error:
                print("Errors:")
                print(error)
            
            # Wait a bit between commands
            time.sleep(2)
        
        print("\n" + "=" * 50)
        print("All commands completed!")
        
    except paramiko.AuthenticationException:
        print("Authentication failed. Please check your username and password.")
        sys.exit(1)
    except paramiko.SSHException as e:
        print(f"SSH error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error connecting to {hostname}: {e}")
        sys.exit(1)
    finally:
        # Close the connection
        if 'ssh_client' in locals():
            ssh_client.close()
            print("SSH connection closed.")

if __name__ == "__main__":
    print("OpenWrt Router SSH Setup Script")
    print("=" * 40)
    ssh_connect_and_run_commands()
