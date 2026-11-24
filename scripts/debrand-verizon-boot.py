#!/usr/bin/env python3
"""Automate Verizon boot debranding on rooted Motorola Moto G Power 2026 (vegas26, XT2617V).

Builds and deploys a systemless Magisk / KernelSU / APatch module that overrides
carrier-specific Verizon boot animations with the stock unbranded Motorola
"Hello Moto" animation across all carrier targets (tracfone, vzw, vzwpre).
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

EXPECTED_DEVICE = r"^vegas(?:26)?$"
EXPECTED_SKU = r"^XT2617V$"
CARRIERS = ("tracfone", "vzw", "vzwpre")
MODULE_ID = "vegas26_verizon_debranding"
MODULE_NAME = "Motorola Verizon Boot Debranding"
MODULE_VERSION = "1.0.0"
MODULE_VERSION_CODE = 1
MODULE_AUTHOR = "Local"
MODULE_DESCRIPTION = (
    "Removes Verizon boot branding while preserving the original Motorola "
    "Hello Moto animation."
)


def run_cmd(cmd, check=True):
    """Run a host shell command and return stdout decoded."""
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n{result.stderr}"
        )
    return result


def adb_cmd(args, serial=None):
    """Construct ADB command with optional serial."""
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return cmd


def adb_shell(cmd_str, serial=None, root=False):
    """Execute shell command on Android via ADB."""
    if root:
        wrapped = f"su --mount-master -c '{cmd_str}'"
    else:
        wrapped = cmd_str
    res = run_cmd(adb_cmd(["shell", wrapped], serial=serial), check=True)
    return res.stdout.strip()


def sha256_file(path):
    """Calculate SHA-256 digest of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_target_device(serial=None):
    """Verify connected device meets hardware, SKU, and root requirements."""
    print("[-] Checking connected device...")
    devices_out = run_cmd(adb_cmd(["devices"]), check=True).stdout.strip().splitlines()
    attached = [
        line.split()[0]
        for line in devices_out[1:]
        if line.strip() and not line.startswith("*") and "device" in line
    ]
    if not attached:
        raise RuntimeError("No authorized ADB device found.")
    if serial and serial not in attached:
        raise RuntimeError(f"Requested device serial {serial} not in attached devices: {attached}")
    target_serial = serial or attached[0]

    device = adb_shell("getprop ro.product.device", serial=target_serial)
    sku = adb_shell("getprop ro.boot.hardware.sku", serial=target_serial)
    release = adb_shell("getprop ro.build.version.release", serial=target_serial)
    carrier = adb_shell("getprop ro.carrier", serial=target_serial)

    print(f"    Device:   {device}")
    print(f"    SKU:      {sku}")
    print(f"    Release:  Android {release}")
    print(f"    Carrier:  {carrier}")

    if not re.match(EXPECTED_DEVICE, device):
        raise RuntimeError(f"Unexpected device codename '{device}' (expected vegas26).")
    if not re.match(EXPECTED_SKU, sku):
        raise RuntimeError(f"Unsupported SKU '{sku}' (expected XT2617V).")

    root_id = adb_shell("id", serial=target_serial, root=True)
    if "uid=0(root)" not in root_id:
        raise RuntimeError(f"Root access check failed: {root_id}")
    print(f"    Root:     Verified ({root_id})")

    return target_serial


def create_module_zip(stock_anim_path, output_zip_path):
    """Build the debranding Magisk / KernelSU / APatch module ZIP."""
    print(f"[-] Building module archive at {output_zip_path}...")

    # Validate stock animation archive
    with zipfile.ZipFile(stock_anim_path, "r") as z:
        if z.testzip() is not None:
            raise ValueError("Corrupt source bootanimation.zip archive.")
        namelist = z.namelist()
        if "01_moto.mp4" not in namelist or "videodesc.txt" not in namelist:
            raise ValueError("source bootanimation.zip missing essential Motorola video assets.")

    module_prop = (
        f"id={MODULE_ID}\n"
        f"name={MODULE_NAME}\n"
        f"version={MODULE_VERSION}\n"
        f"versionCode={MODULE_VERSION_CODE}\n"
        f"author={MODULE_AUTHOR}\n"
        f"description={MODULE_DESCRIPTION}\n"
    )

    customize_sh = (
        'ui_print "**********************************************"\n'
        'ui_print "*   Motorola Verizon Boot Debranding Module  *"\n'
        'ui_print "*        for Moto G Power 2026 (vegas26)     *"\n'
        'ui_print "**********************************************"\n'
        'ui_print "- Device codename: $DEVICE"\n'
        'ui_print "- Android Version: $(getprop ro.build.version.release)"\n'
        'ui_print "- Current carrier: $(getprop ro.carrier)"\n'
        'ui_print "- Deploying unbranded Motorola boot animation..."\n'
        'set_perm_recursive "$MODPATH" 0 0 0755 0644\n'
        'set_perm "$MODPATH/post-fs-data.sh" 0 0 0755\n'
        'ui_print "- Module successfully installed!"\n'
        'ui_print "- Reboot phone to enjoy clean Hello Moto animation."\n'
    )

    post_fs_data_sh = (
        "#!/system/bin/sh\n"
        "# Motorola Vegas 26 Verizon Debranding - post-fs-data hook\n"
        "MODDIR=${0%/*}\n"
        'LOGFILE="/data/local/tmp/verizon_debranding.log"\n'
        '\necho "=== Verizon Debranding post-fs-data $(date) ===" > "$LOGFILE"\n'
        'echo "MODDIR: $MODDIR" >> "$LOGFILE"\n'
        "\nfor carrier_name in tracfone vzw vzwpre; do\n"
        '    target="/product/carrier/$carrier_name/media/bootanimation.zip"\n'
        '    source="$MODDIR/system/product/carrier/$carrier_name/media/bootanimation.zip"\n'
        '    if [ -f "$target" ] && [ -f "$source" ]; then\n'
        '        if grep -q "$target" /proc/mounts; then\n'
        '            echo "$target already mounted by magic mount" >> "$LOGFILE"\n'
        "        else\n"
        '            mount -o bind "$source" "$target" 2>> "$LOGFILE" && \\\n'
        '                echo "Explicitly bind-mounted $source -> $target" >> "$LOGFILE" || \\\n'
        '                echo "Failed to bind-mount $target" >> "$LOGFILE"\n'
        "        fi\n"
        "    fi\n"
        "done\n"
    )

    update_binary = (
        "#!/sbin/sh\n"
        "umask 022\n"
        "OUTFD=$2\n"
        "ZIPFILE=$3\n"
        "if [ -f /data/adb/magisk/util_functions.sh ]; then\n"
        "  . /data/adb/magisk/util_functions.sh\n"
        "elif [ -f /data/adb/ksu/bin/util_functions.sh ]; then\n"
        "  . /data/adb/ksu/bin/util_functions.sh\n"
        "elif [ -f /data/adb/ap/bin/util_functions.sh ]; then\n"
        "  . /data/adb/ap/bin/util_functions.sh\n"
        "else\n"
        '  echo "! util_functions.sh not found!" >&2\n'
        "  exit 1\n"
        "fi\n"
        "install_module\n"
        "exit 0\n"
    )

    updater_script = "#MAGISK\n"

    output_zip_path = Path(output_zip_path)
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("module.prop", module_prop)
        z.writestr("customize.sh", customize_sh)
        z.writestr("post-fs-data.sh", post_fs_data_sh)
        z.writestr("META-INF/com/google/android/update-binary", update_binary)
        z.writestr("META-INF/com/google/android/updater-script", updater_script)

        # Write clean bootanimation.zip uncompressed (STORED) for each carrier
        with open(stock_anim_path, "rb") as bf:
            anim_bytes = bf.read()
        for carrier in CARRIERS:
            dest_in_zip = f"system/product/carrier/{carrier}/media/bootanimation.zip"
            zinfo = zipfile.ZipInfo(dest_in_zip)
            zinfo.compress_type = zipfile.ZIP_STORED
            z.writestr(zinfo, anim_bytes)

    print(f"    SHA-256: {sha256_file(output_zip_path)}")


def install_module_on_device(zip_path, serial=None):
    """Push and install the module on connected device."""
    target_remote_zip = "/data/local/tmp/vegas26_verizon_debranding.zip"
    print(f"[-] Pushing module to {target_remote_zip}...")
    run_cmd(adb_cmd(["push", str(zip_path), target_remote_zip], serial=serial), check=True)

    print("[-] Installing module via root utility...")
    install_res = adb_shell(
        f"magisk --install-module {target_remote_zip}",
        serial=serial,
        root=True,
    )
    print(install_res)

    # Clean up installer archive on device
    adb_shell(f"rm -f {target_remote_zip}", serial=serial, root=True)

    # Ensure files are mirrored into active module folder immediately
    adb_shell(
        "if [ -d /data/adb/modules_update/vegas26_verizon_debranding ]; then "
        "  cp -a /data/adb/modules_update/vegas26_verizon_debranding/* "
        "        /data/adb/modules/vegas26_verizon_debranding/ 2>/dev/null || true; "
        "fi",
        serial=serial,
        root=True,
    )
    print("[+] Module installed successfully.")


def uninstall_module_on_device(serial=None):
    """Remove debranding module from device."""
    print("[-] Removing debranding module...")
    adb_shell(
        f"rm -rf /data/adb/modules/{MODULE_ID} /data/adb/modules_update/{MODULE_ID}",
        serial=serial,
        root=True,
    )
    print("[+] Module removed. Reboot phone to restore factory carrier branding.")


def verify_device_status(serial=None):
    """Audit active boot animation mounts and module state."""
    print("[-] Auditing debranding status on device...")
    is_installed = adb_shell(
        f"[ -d /data/adb/modules/{MODULE_ID} ] && echo YES || echo NO",
        serial=serial,
        root=True,
    )
    print(f"    Module installed: {is_installed}")

    for carrier in CARRIERS:
        path = f"/product/carrier/{carrier}/media/bootanimation.zip"
        digest = adb_shell(
            f"sha256sum {path} 2>/dev/null || echo 'NOT FOUND'",
            serial=serial,
            root=True,
        )
        print(f"    {carrier:10s} {digest}")


def main():
    parser = argparse.ArgumentParser(
        description="Debrand Verizon boot animation on rooted Moto G Power 2026 (vegas26, XT2617V)."
    )
    parser.add_argument("-s", "--serial", help="ADB device serial.")
    parser.add_argument(
        "--package-only",
        action="store_true",
        help="Build flashable module ZIP locally without installing on device.",
    )
    parser.add_argument(
        "--output",
        default="verizon-debranding/vegas26_verizon_debranding.zip",
        help="Output path for the generated module ZIP.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove debranding module from connected device.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Audit debranding status and active digests on connected device.",
    )
    parser.add_argument(
        "--reboot",
        action="store_true",
        help="Reboot device after installation.",
    )

    args = parser.parse_args()

    serial = verify_target_device(serial=args.serial)

    if args.uninstall:
        uninstall_module_on_device(serial=serial)
        if args.reboot:
            run_cmd(adb_cmd(["reboot"], serial=serial))
        return 0

    if args.verify:
        verify_device_status(serial=serial)
        return 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        stock_anim = Path(tmp_dir) / "stock_bootanimation.zip"
        print("[-] Pulling clean Motorola animation from /product/media/bootanimation.zip...")
        run_cmd(
            adb_cmd(["pull", "/product/media/bootanimation.zip", str(stock_anim)], serial=serial),
            check=True,
        )
        create_module_zip(stock_anim, args.output)

    if args.package_only:
        print(f"[+] Module built at {args.output}. Skipping deployment as requested.")
        return 0

    install_module_on_device(args.output, serial=serial)

    if args.reboot:
        print("[-] Rebooting device...")
        run_cmd(adb_cmd(["reboot"], serial=serial))
        print("[+] Reboot command sent.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
