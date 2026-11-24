"""Mount the K3s ext4 image inside the private Debian runtime."""

import argparse
import fcntl
import os
from pathlib import Path
import stat
import subprocess


IMAGE = Path("/var/lib/k3s-root.img")
TARGET = Path("/var/lib/vegas26-k3s-storage")
STATE = Path("/run/vegas26-k3s-loop")
CONTROL = Path("/dev/loop-control")
LOOP_CTL_GET_FREE = 0x4C82


def run(*args):
    subprocess.run(args, check=True)


def mount_source():
    result = subprocess.run(
        ("findmnt", "--mountpoint", TARGET, "--noheadings", "--output", "SOURCE"),
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):
        result.check_returncode()
    return result.stdout.strip()


def release():
    if not STATE.exists():
        if mount_source():
            raise RuntimeError(f"Unexpected mount on {TARGET}")
        return
    device = STATE.read_text().strip()
    source = mount_source()
    if source and source != device:
        raise RuntimeError(f"Unexpected mount source on {TARGET}: {source}")
    if source:
        run("umount", TARGET)
    run("losetup", "--detach", device)
    Path(device).unlink()
    STATE.unlink()


def setup():
    if STATE.exists():
        if mount_source() == STATE.read_text().strip():
            return
        release()
    if not IMAGE.is_file() or IMAGE.is_symlink():
        raise RuntimeError(f"Expected a regular image at {IMAGE}")
    TARGET.mkdir(mode=0o700, exist_ok=True)
    if mount_source() or any(TARGET.iterdir()):
        raise RuntimeError(f"Expected an empty mountpoint at {TARGET}")
    if not CONTROL.exists():
        os.mknod(CONTROL, stat.S_IFCHR | 0o600, os.makedev(10, 237))
    with CONTROL.open("rb") as control:
        number = fcntl.ioctl(control, LOOP_CTL_GET_FREE)
    major, minor = map(int, Path(f"/sys/class/block/loop{number}/dev").read_text().split(":"))
    device = Path(f"/dev/vegas26-k3s-loop{number}")
    os.mknod(device, stat.S_IFBLK | 0o600, os.makedev(major, minor))
    try:
        run("losetup", "--direct-io=on", "--sector-size", "4096", device, IMAGE)
    except subprocess.CalledProcessError:
        device.unlink()
        raise
    STATE.write_text(f"{device}\n")
    try:
        if Path(f"/sys/class/block/loop{number}/loop/dio").read_text().strip() != "1":
            raise RuntimeError("The loop device did not enable direct I/O")
        run("mount", "-t", "ext4", "-o", "rw,suid,dev,exec", device, TARGET)
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        release()
        raise


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("mount", "unmount"))
    args = parser.parse_args()
    with Path("/run/vegas26-k3s-storage.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (setup if args.action == "mount" else release)()
