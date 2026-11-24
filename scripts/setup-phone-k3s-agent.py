"""Configure and install K3s worker agent and dependencies on a vegas26 device."""

import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_shell(adb, serial, command, timeout=120, check=True):
    cmd = [adb]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["shell", f"su -c {shlex.quote(command)}"])
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed (exit {res.returncode}): {command}\nStderr: {res.stderr}\nStdout: {res.stdout}")
    return res


def upload_content(adb, serial, content_bytes, destination):
    cmd = [adb]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(["exec-in", f"su -c {shlex.quote(f'umask 077; cat > {destination}')}"])
    subprocess.run(cmd, input=content_bytes, check=True, timeout=180)
    expected = hashlib.sha256(content_bytes).hexdigest()
    res = run_shell(adb, serial, f"sha256sum {destination}")
    actual = res.stdout.split()[0]
    if actual != expected:
        raise RuntimeError(f"Checksum mismatch for {destination}: {actual} != {expected}")


def upload_file(adb, serial, source_path, destination):
    data = source_path.read_bytes()
    upload_content(adb, serial, data, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=os.environ.get("ADB", "/mnt/c/Users/antbl/MotoRoot/platform-tools/adb.exe"))
    parser.add_argument("-s", "--serial", required=True)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--node-ip", required=True)
    parser.add_argument("--node-cidr", required=True)
    parser.add_argument("--wg-privkey", required=True)
    parser.add_argument("--peer-endpoint", required=True, help="Other phone's IP:port")
    parser.add_argument("--peer-pubkey", required=True, help="Other phone's WireGuard pubkey")
    parser.add_argument("--peer-wg-ip", required=True, help="Other phone's WireGuard IP")
    parser.add_argument("--vm-pubkey", default="lpTPX8J9XkFsev7eFE0GSa4eWwtcR/4W+0tcC83Wmnc=")
    parser.add_argument("--vm-wg-ip", default="10.200.0.1")
    parser.add_argument("--token-file", default=Path("/home/antblu/.cache/vegas26-k3s-lab/control-plane-wsl/data/server/token"))
    parser.add_argument("--k3s-binary", default=Path("/home/antblu/.cache/vegas26-k3s-lab/k3s-arm64"))
    args = parser.parse_args()

    root = "/data/adb/debian-trixie"
    conf_dir = f"{root}/etc/rancher/k3s/vegas26-lab"

    print(f"[{args.serial}] 1. Creating K3s directories...")
    run_shell(args.adb, args.serial, f"umask 077; mkdir -p {conf_dir} {root}/usr/local/bin")

    print(f"[{args.serial}] 2. Staging k3s-arm64 binary...")
    k3s_dest = f"{root}/usr/local/bin/k3s"
    # Check if existing binary matches
    check_k3s = run_shell(args.adb, args.serial, f"test -x {k3s_dest} && sha256sum {k3s_dest} || true", check=False)
    expected_hash = digest(args.k3s_binary)
    if not check_k3s.stdout or check_k3s.stdout.split()[0] != expected_hash:
        upload_file(args.adb, args.serial, args.k3s_binary, k3s_dest)
        run_shell(args.adb, args.serial, f"chmod 755 {k3s_dest}")
    else:
        print(f"[{args.serial}] k3s binary already up to date ({expected_hash[:12]}).")

    print(f"[{args.serial}] 3. Writing cluster credentials & configs...")
    token = args.token_file.read_text().strip()
    upload_content(args.adb, args.serial, f"{token}\n".encode(), f"{conf_dir}/token")

    config_yaml = f"""server: "https://127.0.0.1:16443"
token-file: "/etc/rancher/k3s/vegas26-lab/token"
node-name: "{args.node_name}"
node-ip: "{args.node_ip}"
flannel-iface: "wg-k3s"
snapshotter: "overlayfs"
prefer-bundled-bin: false
disable-apiserver-lb: true
kubelet-arg:
  - "cgroup-driver=cgroupfs"
  - "cgroup-root=/k3s"
  - "oom-score-adj=-1000"
  - "fail-swap-on=false"
"""
    upload_content(args.adb, args.serial, config_yaml.encode(), f"{conf_dir}/config.yaml")

    wireguard_conf = f"""[Interface]
PrivateKey = {args.wg_privkey}
ListenPort = 51820

[Peer]
PublicKey = {args.vm_pubkey}
AllowedIPs = {args.vm_wg_ip}/32

[Peer]
PublicKey = {args.peer_pubkey}
AllowedIPs = {args.peer_wg_ip}/32
Endpoint = {args.peer_endpoint}
PersistentKeepalive = 25
"""
    upload_content(args.adb, args.serial, wireguard_conf.encode(), f"{conf_dir}/wireguard.conf")

    upload_content(args.adb, args.serial, f"{args.node_ip}/24 1120\n".encode(), f"{conf_dir}/wireguard-network.conf")
    upload_content(args.adb, args.serial, f"10.42.0.0/16 10.43.0.0/16 {args.node_cidr}\n".encode(), f"{conf_dir}/network.conf")
    upload_content(args.adb, args.serial, b"172.22.126.57:16443 127.0.0.1:16443 10.43.0.1:443\n", f"{conf_dir}/transport.conf")
    run_shell(args.adb, args.serial, f"touch {conf_dir}/ext4-storage {conf_dir}/keep-awake {conf_dir}/allow-uid-65532")

    print(f"[{args.serial}] 4. Installing Debian packages and supervisor service...")
    cmd_install = [
        sys.executable, "scripts/install-debian.py",
        "--adb", args.adb, "-s", args.serial,
        "--reuse", "--k3s-service",
    ]
    subprocess.run(cmd_install, check=True)

    print(f"[{args.serial}] 5. Ensuring ext4 loop image exists...")
    check_img = run_shell(args.adb, args.serial, f"/data/adb/debian-shell test -f /var/lib/k3s-root.img && echo EXISTS || echo MISSING")
    if "EXISTS" not in check_img.stdout:
        print(f"[{args.serial}] Creating 8G ext4 image /var/lib/k3s-root.img...")
        run_shell(
            args.adb, args.serial,
            "/data/adb/debian-shell /bin/sh -ec 'umask 077; fallocate -l 8G /var/lib/k3s-root.img && mkfs.ext4 -F -b 4096 /var/lib/k3s-root.img'",
            timeout=180,
        )
    else:
        print(f"[{args.serial}] /var/lib/k3s-root.img already exists.")

    print(f"[{args.serial}] Setup complete!")


if __name__ == "__main__":
    main()
