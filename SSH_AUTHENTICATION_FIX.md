# SSH Authentication Fix for ZeroTier Installation Script

## Problem

The original `install_zerotier_optimized.py` script was failing to authenticate with OpenWrt routers despite successful manual SSH connections. The script was using the Paramiko library for SSH connections, which was unable to properly authenticate with the router.

## Solution

The script has been modified to use external SSH commands instead of the Paramiko library. This approach leverages the same SSH command that works when manually connecting to the router.

### Key Changes

1. **Removed Paramiko Authentication**
   - Eliminated all Paramiko-based authentication attempts
   - Removed keyboard-interactive and password authentication methods that were failing

2. **Implemented External SSH Command Approach**
   - Created a custom SSH client that uses the system's `ssh` command
   - Added proper file-like object wrappers for command output
   - Maintained compatibility with the rest of the script

3. **Added Connection Testing**
   - Added a test connection to verify SSH works before proceeding with installation
   - Improved error messages with clear troubleshooting steps

4. **Known Hosts Management**
   - Maintained the functionality to remove entries from the SSH known_hosts file
   - Prevents host key verification errors when connecting to the router

## Usage

The script works the same way as before:

```bash
python install_zerotier_optimized.py
```

The script will now:
1. Remove any existing entries for the router in your SSH known_hosts file
2. Test the SSH connection using the external SSH command
3. If successful, proceed with ZeroTier installation
4. If unsuccessful, provide clear error messages and troubleshooting steps

## Troubleshooting

If you encounter SSH connection issues:

1. Verify you can manually SSH to the router: `ssh root@192.168.1.1`
2. Check if your router requires a password
3. Verify the router's IP address is correct (default: 192.168.1.1)
4. Ensure SSH is enabled on your router

## Technical Details

The script now uses a custom `ExternalSSHClient` class that mimics the Paramiko SSH client interface but uses subprocess to run SSH commands. This approach ensures compatibility with the rest of the script while fixing the authentication issue.