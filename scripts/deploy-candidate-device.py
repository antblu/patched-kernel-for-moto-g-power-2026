"""Deploy candidate kernel and init_boot to a verified vegas26 device."""

import hashlib
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

adb_exe = Path(r"C:\Users\antbl\MotoRoot\platform-tools\adb.exe")
fastboot_exe = Path(r"C:\Users\antbl\MotoRoot\platform-tools\fastboot.exe")

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <serial>", file=sys.stderr)
    sys.exit(2)

serial = sys.argv[1]
adb = [str(adb_exe), "-s", serial]
fastboot = [str(fastboot_exe), "-s", serial]

repo_root = Path(r"C:\Users\antbl\Documents\custom-kernel-for-moto-g-power-2026")
kernel = repo_root / ".cache/k3s-active-baseline/boot-unified-physdev-v4.img"
ramdisk = repo_root / ".cache/webview-cgroup-canary/init_boot-zero-err.img"
stock = Path(r"C:\Users\antbl\MotoRoot\private-backups\boot_a.img")
stock_magisk = Path(r"C:\Users\antbl\MotoRoot\magisk-patched-init_boot.img")

kernel_hash = "4a6ad4606f2c88a783aa808d852cf79b1925a74ac76bd681dec7a470f4de5439"
ramdisk_hash = "5d0c140c61ec4f15f3e4e34a9a616b0030128e617df8e00adc5bf97abb4d3da9"
stock_hash = "32a0ba7c3028d0323726f119133ad63a0fc0bd9d4005ba03459b7e1258250e8f"
magisk_hash = "fbac252d15501e8350b65ae93a92962f93d2907144286c04abf2eeda26c246d0"
library_hash = "774186e3adf5edaf69d1e214198743f9a2d156fd94a813496287e9e21b5b57aa"


def run(tool, *args, timeout=15, check=True):
    return subprocess.run(tool + list(args), text=True, capture_output=True,
                          timeout=timeout, check=check)


def root(command):
    return run(adb, "shell", "su -c " + shlex.quote(command), timeout=25).stdout.strip()


def fastboot_target():
    print(f"Waiting for Fastboot target {serial}...", flush=True)
    end = time.monotonic() + 65
    while time.monotonic() < end:
        result = run([str(fastboot_exe)], "devices", check=False)
        if any(line.split()[:1] == [serial] for line in result.stdout.splitlines()):
            break
        time.sleep(2)
    else:
        raise RuntimeError("Fastboot did not reconnect")
    for key, expected in (
        ("product", "vegas"), ("sku", "XT2617V"), ("current-slot", "a"),
        ("securestate", "flashing_unlocked"), ("is-userspace", "no"),
        ("partition-size:boot_a", "0x0000000004000000"),
    ):
        result = run(fastboot, "getvar", key)
        if not re.search(r"^" + re.escape(key) + r":[ \t]*" + re.escape(expected) + r"\s*$",
                         result.stdout + result.stderr, re.M):
            raise RuntimeError(f"Fastboot {key} did not match")
    print("Fastboot target variables verified OK", flush=True)


# 1. Verify host images
print(f"Verifying host image files for deployment to {serial}...", flush=True)
for file, digest in ((kernel, kernel_hash), (ramdisk, ramdisk_hash),
                     (stock, stock_hash), (stock_magisk, magisk_hash)):
    with file.open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == digest
assert ramdisk.stat().st_size == stock_magisk.stat().st_size == 8388608
assert kernel.stat().st_size < stock.stat().st_size == 67108864

# 2. Verify target device
print("Verifying target device properties...", flush=True)
assert root("getprop ro.product.device; getprop ro.build.id; getprop ro.boot.slot_suffix; "
            "getprop sys.boot_completed; getenforce").splitlines() == [
    "vegas26", "W1WEOS36.48-22-3-3-4-2", "_a", "1", "Enforcing",
]
partition = "/dev/block/by-name/init_boot_a"
hashes = root(f"sha256sum /dev/block/by-name/boot_a {partition}").splitlines()
assert [line.split()[0] for line in hashes] == [stock_hash, magisk_hash]
assert root(f"blockdev --getsize64 {partition}") == "8388608"

# 3. Stage candidate init_boot
remote = "/data/adb/vegas26-retry-candidate-" + uuid.uuid4().hex
try:
    print(f"Uploading candidate init_boot to {remote}...", flush=True)
    with ramdisk.open("rb") as source:
        subprocess.run(adb + ["exec-in", "su -c " + shlex.quote("umask 077; cat > " + remote)],
                       stdin=source, check=True, timeout=25)
    assert root("sha256sum " + remote).split()[0] == ramdisk_hash
    print("Writing candidate init_boot to /dev/block/by-name/init_boot_a...", flush=True)
    root(f'test "$(getprop ro.boot.slot_suffix)" = _a && '
         f"dd if={remote} of={partition} bs=1048576 conv=fsync 2>/dev/null")
    assert root("sha256sum " + partition).split()[0] == ramdisk_hash
    print("Verified candidate init_boot_a write", flush=True)
finally:
    root("rm -f " + remote)

# 4. Flash candidate boot_a in fastboot
print("Rebooting to bootloader...", flush=True)
run(adb, "reboot", "bootloader")
fastboot_target()
flash = run(fastboot, "flash", "boot_a", str(kernel), timeout=60, check=False)
print(flash.stdout + flash.stderr, end="", flush=True)
flash.check_returncode()
print("Rebooting device from fastboot...", flush=True)
run(fastboot, "reboot")

# 5. Wait for Android boot
last = ""
deadline = time.monotonic() + 210
print("Waiting for Android boot completion...", flush=True)
while time.monotonic() < deadline:
    time.sleep(3)
    try:
        state = run(adb, "get-state", timeout=7, check=False).stdout.strip() or "disconnected"
        if state != last:
            print("USB state:", state, flush=True)
            last = state
        if state == "recovery":
            raise RuntimeError("The candidate device entered recovery")
        if state != "device":
            continue
        boot = run(adb, "shell", "getprop sys.boot_completed; getprop ro.boot.slot_suffix; getenforce")
        if boot.stdout.splitlines() != ["1", "_a", "Enforcing"]:
            continue
        assert "cgroup_no_v1=all,named" in root("cat /proc/cmdline").split()
        assert root("sha256sum " + partition).split()[0] == ramdisk_hash
        assert root(f"head -c {kernel.stat().st_size} /dev/block/by-name/boot_a | sha256sum").split()[0] == kernel_hash
        for name in ("zygote64", "system_server"):
            pid = root(f"pidof -s {name}").strip()
            path = f"/proc/{pid}/root/system/lib64/libprocessgroup.so"
            assert root("sha256sum " + path).split()[0] == library_hash
            root(rf'''inode=$(stat -Lc %i {path}); pid={pid};
                awk -v inode="$inode" '$2 ~ /^r.xp$/ && $5 == inode && $6 ~ /libprocessgroup\.so$/ {{ found=1 }} END {{ exit !found }}' "/proc/$pid/maps"''')
            print(f"{name} (pid {pid}) maps the verified retry candidate", flush=True)
        print("Device boot and controller verification PASSED!", flush=True)
        break
    except subprocess.TimeoutExpired:
        continue
else:
    raise RuntimeError("Android boot did not verify")

# 6. Run WebView validation
print("Running WebView isolated renderer validation...", flush=True)
result = subprocess.run([sys.executable, str(repo_root / "tests/test-webview-phone.py"),
                         "--adb", str(adb_exe), "--serial", serial, "--iterations",
                         "10", "--require-unified"], timeout=240)
if result.returncode != 0:
    print("WebView validation returned failure code:", result.returncode, file=sys.stderr)
    sys.exit(result.returncode)

print(f"Deployment and verification to {serial} completed successfully!", flush=True)
