#!/usr/bin/env python3
import argparse, time, socket, sys, paramiko

DEFAULT_PORT = 22
DEFAULT_USER = "root"
DEFAULT_HOST = "192.168.1.1"
DEFAULT_NETWORK_ID = "56374ac9a4f632db"
SSH_CONNECT_TIMEOUT = 10
COMMAND_TIMEOUT = 300

def run_cmd(ssh, cmd, timeout=COMMAND_TIMEOUT):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace')
    err = stderr.read().decode('utf-8', errors='replace')
    rc = stdout.channel.recv_exit_status()
    return rc, out.strip(), err.strip()

def wait_ssh(host, port=22, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            return True
        except Exception:
            time.sleep(2)
    return False

def connect_ssh(host, user, port, key_filename, password, force_password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # If force_password: don't look for keys/agent; send password even if it's "".
    allow_agent = not force_password
    look_for_keys = not force_password

    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            key_filename=key_filename,
            password=password,            # can be ""
            timeout=SSH_CONNECT_TIMEOUT,
            allow_agent=allow_agent,
            look_for_keys=look_for_keys,
            banner_timeout=SSH_CONNECT_TIMEOUT,
            auth_timeout=SSH_CONNECT_TIMEOUT,
        )
        return client
    except paramiko.ssh_exception.BadAuthenticationType as e:
        # Server advertised auth types but they didn't match what we tried.
        print(f"Server requires one of these auth methods: {e.allowed_types}")
        raise
    except paramiko.ssh_exception.AuthenticationException as e:
        print("Authentication failed. If your password is empty, be sure to pass --password \"\" and --force-password.")
        raise
    except Exception:
        raise

def main():
    p = argparse.ArgumentParser(description="Install & configure ZeroTier on OpenWrt via SSH.")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--key", default=None, help="Private key file (optional)")
    p.add_argument("--password", default=None, help="Password; use \"\" for empty password")
    p.add_argument("--force-password", action="store_true",
                   help="Force password auth (disable key/agent). Use with --password (can be empty).")
    p.add_argument("--reboot", action="store_true", help="Reboot after config")
    args = p.parse_args()

    print(f"Connecting to {args.user}@{args.host}:{args.port} ...")
    try:
        ssh = connect_ssh(args.host, args.user, args.port, args.key, args.password, args.force_password)
    except Exception as e:
        print("SSH connection failed:", e)
        sys.exit(1)

    try:
        print("Running: opkg update")
        rc, out, err = run_cmd(ssh, "opkg update")
        print(out or "", err or "")

        print("Installing zerotier ...")
        rc, out, err = run_cmd(ssh, "opkg install zerotier")
        print(out or "", err or "")
        if rc != 0:
            print("opkg install failed; aborting.")
            sys.exit(1)

        print("Configuring /etc/config/zerotier ...")
        cmds = [
            "uci set zerotier.global.enabled='1'",
            "uci delete zerotier.earth || true",
            "uci set zerotier.myzt=network",
            f"uci set zerotier.myzt.id='{DEFAULT_NETWORK_ID}'",
            "uci commit zerotier",
            "/etc/init.d/zerotier enable",
            "/etc/init.d/zerotier start"
        ]
        rc, out, err = run_cmd(ssh, " && ".join(cmds))
        print(out or "", err or "")

        if args.reboot:
            print("Rebooting router ...")
            try: run_cmd(ssh, "reboot || true")
            except Exception: pass
            try: ssh.close()
            except: pass
            print("Waiting for SSH to return ...")
            if not wait_ssh(args.host, port=args.port, timeout=180):
                print("Timed out waiting after reboot.")
                sys.exit(1)
            ssh = connect_ssh(args.host, args.user, args.port, args.key, args.password, args.force_password)

        print("Checking for zt interface ...")
        rc, out, err = run_cmd(ssh, "ip a || true")
        print(out or "")
        if "zt" not in out:
            print("Note: 'zt' interface not found yet. Approve the node in ZeroTier Central, then check again.")

        print(f"\nDONE. Authorize the node on https://my.zerotier.com for network {DEFAULT_NETWORK_ID}.")
    finally:
        try: ssh.close()
        except: pass

if __name__ == "__main__":
    main()
