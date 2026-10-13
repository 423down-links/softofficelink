#!/usr/bin/env python3
"""Register a new SSH host in ~/.ssh/config and ~/.ssh/hosts.json.

Usage:
    register-host.py <alias> <host> <user> <purpose>
    register-host.py <alias> <host> <port> <user> <purpose>

The host block uses ProxyCommand to tunnel through the sandbox HTTP proxy
(direct port 22 is blocked). IdentityFile defaults to ~/.ssh/id_ed25519.
"""
import json, os, re, sys

PROXY = "127.0.0.1:18080"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")  # 防 ~/.ssh/config 注入（换行/空格/等号等一律拒绝）


def main():
    args = sys.argv[1:]
    if len(args) == 4:
        alias, host, user, purpose = args
        port = 22
    elif len(args) == 5:
        alias, host, port, user, purpose = args
        port = int(port)
    else:
        print(__doc__)
        sys.exit(2)

    for kind, val in (("alias", alias), ("host", host), ("user", user)):
        if not SAFE_TOKEN.match(val):
            print(f"ERROR: 非法 {kind}: {val!r}（只允许 [A-Za-z0-9._-]，拒绝 config 注入）")
            sys.exit(2)

    ssh_dir = os.path.expanduser("~/.ssh")
    os.makedirs(ssh_dir, exist_ok=True)
    os.chmod(ssh_dir, 0o700)
    config = os.path.join(ssh_dir, "config")

    if os.path.exists(config):
        with open(config) as f:
            existing = f.read()
        # match "Host alias " or "Host alias\n"
        for line in existing.splitlines():
            line = line.strip()
            if line.startswith("Host ") and line.split(None, 1)[1].split() == [alias]:
                print(f"Host {alias} already exists in {config}; edit manually to change.")
                sys.exit(1)

    block = f"""
Host {alias}
    HostName {host}
    Port {port}
    User {user}
    ProxyCommand nc -X connect -x {PROXY} %h %p
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    IdentityFile ~/.ssh/id_ed25519
"""
    with open(config, "a") as f:
        f.write(block)
    os.chmod(config, 0o600)

    reg_path = os.path.join(ssh_dir, "hosts.json")
    if os.path.exists(reg_path):
        try:
            reg = json.load(open(reg_path))
        except json.JSONDecodeError:
            reg = []
    else:
        reg = []
    if not any(h.get("alias") == alias for h in reg):
        reg.append({"alias": alias, "host": host, "port": port,
                    "user": user, "purpose": purpose})
    with open(reg_path, "w") as f:
        json.dump(reg, f, indent=2, ensure_ascii=False)
    os.chmod(reg_path, 0o600)

    print(f"Registered {alias} -> {user}@{host}:{port} ({purpose})")
    print(f"Next: bootstrap-key.py --host {host} --port {port} --user {user}  (password via stdin)")


if __name__ == "__main__":
    main()
