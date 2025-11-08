#!/usr/bin/env python3
"""
openwrt_zerotier_setup.py

Install & configure ZeroTier on an OpenWrt router via SSH.
Supports:
 - SSH key auth (--key)
 - SSH password auth (--password). Default user: root, default password: root
 - Optionally force password auth (--force-password)
 - Optionally reboot after config (--reboot)

Default ZeroTier network ID: 56374ac9a4f632db
"""
from __future__ import annotations
import argparse
import socket
import sys
import time
import paramiko

DEFAULT_HOST = "192.168.1.1"
DEFAULT_PORT = 22
DEFAULT_USER = "root"
DEFAULT_PASSWORD = "root"            # per your request
DEFAULT_NETWORK_ID = "56374ac9a4f632db"
SSH_CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 300

def run_cmd(ssh: paramiko.SSHClient, cmd: str, timeout: int = COMMAND_TIMEOUT):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out.strip(), err.strip()

def wait_ssh(host: str, port: int = DEFAULT_PORT, timeout: int = 180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            return True
        except Exception:
            time.sleep(2)
    return False

def connect_ssh(host: str, port: int, username: str, key_filename: str | None, password: str | None, force_password: bool):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    allow_agent = not force_password
    look_for_keys = not force_password

    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            key_filename=key_filename,
            password=password,
            timeout=SSH_CONNECT_TIMEOUT,
            allow_agent=allow_agent,
            look_for_keys=look_for_keys,
            banner_timeout=SSH_CONNECT_TIMEOUT,
            auth_timeout=SSH_CONNECT_TIMEOUT,
        )
        return client
    except paramiko.ssh_exception.AuthenticationException as e:
        raise e
    except paramiko.ssh_exception.BadAuthenticationType as e:
        # show what server accepts
        raise RuntimeError(f"Server requires auth types: {getattr(e, 'allowed_types', 'unknown')}") from e
    except Exception as e:
        raise

def ensure_zerotier_configured(ssh: paramiko.SSHClient, network_id: str):
    # Ensure package installed & service enabled, then add network via uci add
    print("Running opkg update && opkg install zerotier (if not present)...")
    rc, out, err = run_cmd(ssh, "opkg update && opkg install zerotier || true")
    print(out or "", err or "")

    # enable & start service
    print("Enabling & starting zerotier service...")
    rc, out, err = run_cmd(ssh, "/etc/init.d/zerotier enable || true; /etc/init.d/zerotier start || true; /etc/init.d/zerotier status || true")
    print(out or "", err or "")

    # Add network entry via uci add (OpenWrt-friendly). Use @network[-1] to reference last added
    print(f"Adding ZeroTier network id '{network_id}' to /etc/config/zerotier using UCI...")
    uci_cmds = (
        "uci show zerotier >/dev/null 2>&1 || touch /etc/config/zerotier; "
        "uci add zerotier network; "
        f"uci set zerotier.@network[-1].id='{network_id}'; "
        "uci commit zerotier; "
        "/etc/init.d/zerotier restart || true; "
        "sleep 2; "
        "echo 'UCI-DUMP-FOLLOW'; uci show zerotier || true"
    )
    rc, out, err = run_cmd(ssh, uci_cmds, timeout=COMMAND_TIMEOUT)
    print(out or "", err or "")

    if rc != 0:
        print("Warning: UCI commands returned non-zero. Inspect output above.")
    # return status for whether zerotier interface present
    rc, out, err = run_cmd(ssh, "zerotier-cli listnetworks || true")
    return rc, out, err

def main():
    p = argparse.ArgumentParser(description="Install & configure ZeroTier on OpenWrt via SSH.")
    p.add_argument("--host", default=DEFAULT_HOST, help="Router host (default 192.168.1.1)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="SSH port (default 22)")
    p.add_argument("--user", default=DEFAULT_USER, help="SSH username (default root)")
    p.add_argument("--key", default=None, help="Private key file path (optional)")
    p.add_argument("--password", default=None, help="Password for SSH (optional). If omitted uses default 'root'. Use empty string '' if you want empty password.")
    p.add_argument("--force-password", action="store_true", help="Force password auth (disable key/agent attempts).")
    p.add_argument("--network-id", default=DEFAULT_NETWORK_ID, help=f"ZeroTier network id (default {DEFAULT_NETWORK_ID})")
    p.add_argument("--reboot", action="store_true", help="Reboot router after configuration (optional)")
    args = p.parse_args()

    host = args.host
    port = args.port
    username = args.user
    keyfile = args.key
    password = args.password if args.password is not None else DEFAULT_PASSWORD
    force_password = args.force_password
    network_id = args.network_id

    tried = []
    ssh = None

    # Try connect: prefer key (unless forced) then password fallback
    # If user explicitly provided --force-password, skip key attempts
    if not force_password:
        try:
            print("Attempting SSH connection (key auth / agent) ...")
            ssh = connect_ssh(host, port, username, keyfile, None, force_password=False)
            print("Connected using key/agent auth.")
        except Exception as e:
            tried.append(("key", str(e)))
            ssh = None

    if ssh is None:
        # Try key file explicitly if provided
        if keyfile and not force_password:
            try:
                print(f"Attempting SSH connection using key file: {keyfile} ...")
                ssh = connect_ssh(host, port, username, keyfile, None, force_password=False)
                print("Connected using provided key file.")
            except Exception as e:
                tried.append(("keyfile", str(e)))
                ssh = None

    if ssh is None:
        # Try password (password can be default 'root' or user-provided; can be empty string)
        try:
            print(f"Attempting SSH connection using password for {username}@{host} ...")
            ssh = connect_ssh(host, port, username, keyfile if keyfile else None, password, force_password=True)
            print("Connected using password auth.")
        except Exception as e:
            tried.append(("password", str(e)))
            ssh = None

    if ssh is None:
        print("All connection attempts failed. Details:")
        for method, msg in tried:
            print(f" - {method}: {msg}")
        print("If server only accepts publickey, upload your public key to the router and retry with --key.")
        sys.exit(1)

    try:
        # Run installation and config
        rc, out, err = ensure_zerotier_configured(ssh, network_id)
        print("zerotier-cli listnetworks output (if any):")
        print(out or err or "(no output)")

        # Optionally reboot
        if args.reboot:
            print("Rebooting router now...")
            try:
                run_cmd(ssh, "reboot || true")
            except Exception:
                # remote closed connection expected
                pass
            ssh.close()
            print("Waiting for SSH to return...")
            if not wait_ssh(host, port, timeout=180):
                print("Timed out waiting for router to come back. Connect manually to inspect.")
                sys.exit(1)
            # reconnect using same auth preference
            # try key again unless forced
            ssh = None
            if not force_password:
                try:
                    ssh = connect_ssh(host, port, username, keyfile, None, force_password=False)
                except Exception:
                    ssh = None
            if ssh is None:
                try:
                    ssh = connect_ssh(host, port, username, keyfile if keyfile else None, password, force_password=True)
                except Exception as e:
                    print("Failed to reconnect after reboot:", e)
                    sys.exit(1)

        # Final check for zt interface
        print("Checking for ZeroTier interface (ip a)...")
        rc, out, err = run_cmd(ssh, "ip a || true")
        print(out or "")
        if "zt" in out:
            print("ZeroTier interface detected. Good.")
        else:
            print("No 'zt' interface found yet. Likely node needs authorization at https://my.zerotier.com for network", network_id)
            print("Run: zerotier-cli listnetworks  OR check ZeroTier Central to authorize the node.")
            rc2, out2, err2 = run_cmd(ssh, "zerotier-cli listnetworks || true")
            if out2:
                print("zerotier-cli listnetworks output:\n", out2)

        print("\nDONE. Next steps:")
        print(f"- Open https://my.zerotier.com and authorize the node for network {network_id} (if required).")
        print("- After authorization, run `ip a` on the router to see the zt... interface.")
    finally:
        try:
            ssh.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
