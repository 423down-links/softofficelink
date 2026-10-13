#!/usr/bin/env python3
"""Bootstrap key-based SSH auth from this sandbox.

The sandbox blocks direct outbound port 22, so SSH must tunnel through the
HTTP proxy at 127.0.0.1:18080 (verified to permit CONNECT to :22). sshpass is
NOT installed here, so this script uses a pty to feed the password once,
installs the local public key on the remote authorized_keys, then verifies
key-based login works.

Password is read from stdin (never an argv) to avoid leaking in process list.

Usage:
    printf '%s' 'PASSWORD' | python3 bootstrap-key.py --host HOST [--port 22] --user USER [--identity ~/.ssh/id_ed25519]

Exit codes: 0=ok, 1=install/verify failed, 2=bad args / no key, 3=timeout
"""
import argparse, base64, os, pty, select, subprocess, sys, time

PROXY = "127.0.0.1:18080"
TIMEOUT = 60  # seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--user", required=True)
    ap.add_argument("--identity", default=os.path.expanduser("~/.ssh/id_ed25519"))
    args = ap.parse_args()

    password = sys.stdin.readline().rstrip("\n")
    if not password:
        print("ERROR: no password on stdin", file=sys.stderr)
        sys.exit(2)

    pubkey_path = args.identity + ".pub"
    if not os.path.exists(pubkey_path):
        print(f"ERROR: {pubkey_path} not found. Run ssh-keygen first.", file=sys.stderr)
        sys.exit(2)
    with open(pubkey_path) as f:
        pubkey = f.read().strip()

    # base64 the pubkey so the shell arg is quote-safe (only [A-Za-z0-9+/=])
    pubkey_b64 = base64.b64encode(pubkey.encode()).decode()
    remote_cmd = (
        "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; "
        f"echo '{pubkey_b64}' | base64 -d >> ~/.ssh/authorized_keys; "
        "echo INSTALLED"
    )

    proxy_cmd = f"nc -X connect -x {PROXY} %h %p"
    ssh_args = [
        "ssh",
        "-o", f"ProxyCommand={proxy_cmd}",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "PubkeyAuthentication=no",
        "-o", f"ConnectTimeout={TIMEOUT}",
        "-p", str(args.port),
        f"{args.user}@{args.host}",
        remote_cmd,
    ]

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(ssh_args[0], ssh_args)

    buf = b""
    fed = False
    start = time.time()
    while True:
        if time.time() - start > TIMEOUT:
            print("ERROR: timeout", file=sys.stderr)
            sys.exit(3)
        try:
            r, _, _ = select.select([fd], [], [], 0.5)
        except OSError:
            break
        if fd in r:
            try:
                data = os.read(fd, 4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            low = data.lower()
            if (b"password" in low or b"yes/no" in low) and not fed:
                if b"yes/no" in low:
                    os.write(fd, b"yes\n")
                if b"password" in low:
                    os.write(fd, password.encode() + b"\n")
                    fed = True
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                try:
                    while True:
                        d = os.read(fd, 4096)
                        if not d:
                            break
                        buf += d
                except OSError:
                    pass
                break
        except ChildProcessError:
            break

    text = buf.decode(errors="replace")
    # strip ANSI noise for readable logging
    import re
    text_clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)

    if "INSTALLED" in text_clean:
        # verify key login works now
        verify = [
            "ssh", "-o", f"ProxyCommand={proxy_cmd}",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"ConnectTimeout={TIMEOUT}",
            "-i", args.identity,
            "-p", str(args.port),
            f"{args.user}@{args.host}",
            "echo KEYLOGIN_OK",
        ]
        rv = subprocess.run(verify, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL).returncode
        if rv == 0:
            print(f"OK: key installed and verified on {args.host}")
            sys.exit(0)
        else:
            print("WARN: install reported OK but key login verify failed; check ~/.ssh perms on remote", file=sys.stderr)
            sys.exit(1)
    else:
        print("FAILED. ssh output (cleaned):", file=sys.stderr)
        print(text_clean[-2000:], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
