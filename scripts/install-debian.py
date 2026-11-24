"""Download and install the tested Debian 13 ARM64 userspace and boot service."""

import argparse
import gzip
import hashlib
import ipaddress
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

IMAGE = "docker.io/library/debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2"
ROOT = "/data/adb/debian-trixie"
BUSYBOX = "/data/adb/magisk/busybox"
LAUNCHER = "/data/adb/debian-shell"
SERVICE = "/data/adb/service.d/90-debian-trixie.sh"
K3S_SERVICE = "/data/adb/service.d/95-vegas26-k3s.sh"
K3S_SCRIPTS = (
    "check-k3s-cgroup-v2.sh", "setup-k3s-cgroup.sh", "run-in-k3s-runtime.sh",
    "k3s-supervisor.sh", "k3s-network.py", "k3s-storage.py", "k3s-wireguard.sh",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def export_rootfs(archive):
    subprocess.run(["docker", "pull", "--platform", "linux/arm64", IMAGE], check=True)
    container = subprocess.check_output(
        ["docker", "create", "--platform", "linux/arm64", IMAGE], text=True
    ).strip()
    try:
        with gzip.open(archive, "wb") as output:
            with subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE) as process:
                shutil.copyfileobj(process.stdout, output)
                if process.wait():
                    raise RuntimeError("Docker root filesystem export failed.")
    finally:
        subprocess.run(["docker", "rm", container], stdout=subprocess.DEVNULL, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    parser.add_argument("-s", "--serial", default=os.environ.get("ADB_SERIAL"))
    parser.add_argument("--archive", type=Path, default=Path(".cache/debian-arm64.tar.gz"))
    parser.add_argument("--reuse", action="store_true", help="Preserve an existing Debian install.")
    parser.add_argument("--k3s-service", action="store_true", help="Install the optional K3s boot service.")
    args = parser.parse_args()
    if args.k3s_service and not args.reuse:
        parser.error("--k3s-service requires --reuse and a configured K3s agent")
    adb = [args.adb]
    if args.serial:
        adb.extend(("-s", args.serial))
    scripts = Path(__file__).resolve().parent

    def shell(command, timeout=25, check=True):
        return subprocess.run(
            [*adb, "shell", "su -c " + shlex.quote(command)], check=check,
            capture_output=True, text=True, timeout=timeout,
        )

    def upload(source, destination):
        with source.open("rb") as stream:
            subprocess.run(
                [*adb, "exec-in", "su -c " + shlex.quote(f"umask 077; cat > {destination}")],
                stdin=stream, check=True, timeout=180,
            )
        received = shell(f"sha256sum {destination}").stdout.split()
        if not received or received[0] != digest(source):
            raise RuntimeError("Transferred file checksum mismatch.")

    device, release = shell("getprop ro.product.device; uname -r").stdout.split()
    if device != "vegas26" or not re.match(r"5\.15\.180(?:-|$)", release):
        raise RuntimeError("Expected the Moto G Power 2026 running the namespace kernel.")
    shell(f"test -x {BUSYBOX} && unshare -p -f true")
    if args.k3s_service:
        shell(f"test -x {ROOT}/usr/local/bin/k3s && "
              f"(test -f {ROOT}/etc/rancher/k3s/vegas26-lab/config.yaml || test -f {ROOT}/etc/rancher/k3s/vegas26/config.yaml)")
    stage = ROOT + ".install-" + uuid.uuid4().hex
    shell(f"umask 077; mkdir {stage}")
    with tempfile.TemporaryDirectory() as work:
        if args.reuse:
            shell(f"test -x {ROOT}/bin/bash && grep -qx VERSION_CODENAME=trixie {ROOT}/etc/os-release")
        else:
            shell(f"test ! -e {ROOT}")
            if args.archive and args.archive.exists():
                archive = args.archive
            else:
                archive = Path(work) / "rootfs.tar.gz"
                export_rootfs(archive)
            upload(archive, f"{stage}/rootfs.tar.gz")
            shell(f"mkdir {stage}/root && {BUSYBOX} tar -xzf {stage}/rootfs.tar.gz -C {stage}/root "
                  f"&& test -x {stage}/root/bin/bash && test ! -e {ROOT} && mv {stage}/root {ROOT} "
                  f"&& rm {stage}/rootfs.tar.gz", timeout=180)

        connectivity = shell("dumpsys connectivity").stdout
        active = re.search(r"Active default network:\s*(\d+)", connectivity)
        if not active:
            raise RuntimeError("Android has no active network for installing tini.")
        servers = []
        for line in connectivity.splitlines():
            if f"network{{{active[1]}}}" not in line.lower():
                continue
            dns = re.search(r"DnsAddresses:\s*\[([^\]]*)\]", line)
            if dns:
                for item in re.split(r"[,\s]+", dns[1]):
                    try:
                        servers.append(str(ipaddress.ip_address(item.strip("/"))))
                    except ValueError:
                        pass
        if not servers:
            raise RuntimeError("Android's active network did not provide DNS servers.")
        resolver = "".join(f"nameserver {server}\n" for server in dict.fromkeys(servers))
        shell(f"printf %s {shlex.quote(resolver)} > {ROOT}/etc/resolv.conf")
        upload(scripts / "debian-shell.sh", f"{stage}/launcher")
        shell(f"mv {stage}/launcher {LAUNCHER} && chmod 700 {LAUNCHER}")
        shell(f"/system/bin/sh {LAUNCHER} apt-get -o APT::Update::Error-Mode=any update", timeout=180)
        shell(f"/system/bin/sh {LAUNCHER} apt-get install -y --no-install-recommends tini", timeout=180)
        upload(scripts / "debian-startup.sh", f"{stage}/startup")
        shell(f"mkdir -p /data/adb/service.d && chmod 700 {stage}/startup "
              f"&& mv {stage}/startup {SERVICE}")
        if args.k3s_service:
            packages = "iproute2 iptables ipset util-linux xtables-addons-common python3 e2fsprogs wireguard-tools bpftool ca-certificates"
            shell(f"/system/bin/sh {LAUNCHER} apt-get install -y --no-install-recommends "
                  f"{packages}", timeout=300)
            shell(f"/system/bin/sh {LAUNCHER} update-alternatives --set iptables /usr/sbin/iptables-legacy")
            shell(f"/system/bin/sh {LAUNCHER} update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy")
            lib = f"{ROOT}/usr/local/lib/vegas26-k3s"
            shell(f"mkdir -p {lib} && test -d {lib}")
            for name in K3S_SCRIPTS:
                upload(scripts / name, f"{stage}/{name}")
                shell(f"mv {stage}/{name} {lib}/{name}")
            upload(scripts / "k3s-startup.sh", f"{stage}/k3s-startup")
            shell(f"chmod 700 {stage}/k3s-startup && mv {stage}/k3s-startup {K3S_SERVICE}")
        shell(f"rmdir {stage}")
    print("Debian is installed. The Magisk startup service runs at the next Android boot.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Debian installer command failed (exit {error.returncode}): {error.cmd}\nStderr: {error.stderr}\nStdout: {error.stdout}") from None
