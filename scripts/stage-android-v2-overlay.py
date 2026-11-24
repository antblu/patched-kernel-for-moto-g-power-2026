"""Prepare the verified vegas26 Android policy and library for Magisk overlay.d."""

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys


LABELS = {
    "system/etc/cgroups.json": "cgroup_desc_file",
    "system/etc/task_profiles.json": "task_profiles_file",
    "system/lib64/libprocessgroup.so": "system_lib_file",
    "system/etc/init/hw/init.rc": "system_file",
    "product/etc/init/init.mmi.product.rc": "system_file",
    "system_ext/etc/init/hw/meta_init.system.rc": "system_file",
    "vendor/etc/cgroups.json": "vendor_cgroup_desc_file",
    "vendor/etc/task_profiles.json": "vendor_task_profiles_file",
    "vendor/etc/init/hw/init.cgroup.rc": "vendor_configs_file",
    "vendor/etc/init/hw/init.mt6835.rc": "vendor_configs_file",
    "vendor/etc/init/hw/factory_init.rc": "vendor_configs_file",
    "vendor/etc/init/vendor.mediatek.hardware.mtkpower@1.0-init.rc": "vendor_configs_file",
}
LIBRARY = "system/lib64/libprocessgroup.so"
MAIN_INIT = "system/etc/init/hw/init.rc"
INIT_INPUT = "vegas26-init.rc.in"
INIT = """on early-init
    exec u:r:magisk:s0 root root -- /system/bin/sh ${MAGISKTMP}/retain-vegas26-v2.sh ${MAGISKTMP}

service vegas26_top_app_watch /system/bin/sh ${MAGISKTMP}/run-vegas26-top-app-bridge.sh --watch ${MAGISKTMP}/update-vegas26-top-app-mask.sh
    disabled
    oneshot
    user root
    group root
    seclabel u:r:magisk:s0

on post-fs-data
    start vegas26_top_app_watch
"""


def transform_init_body(content: str) -> str:
    """Predict the firmware portion of the script written by Magisk v31.1."""
    lines = []
    for line in content.splitlines(keepends=True):
        if "start vaultkeeper" in line:
            continue
        if line.startswith("service flash_recovery"):
            lines.append("service flash_recovery /system/bin/true\n")
            continue
        if line.startswith("on property:persist.sys.zygote.early="):
            lines.append("on property:persist.sys.zygote.early.xxxxx=true\n")
            continue
        lines.append(line)
    return "".join(lines)


def transform_effective_init_rc(content: str, custom_rc: str, tmp_path: str = "/debug_ramdisk") -> str:
    """Build a reference for offline syntax checks of the staged scripts."""
    if not content.endswith("\n"):
        content += "\n"
    script_injected = custom_rc.replace("${MAGISKTMP}", tmp_path)
    out = transform_init_body(content) + f"\n\n{script_injected}\n"

    magisk_rc = (
        "\n"
        "on post-fs-data\n"
        f"    exec u:r:magisk:s0 0 0 -- {tmp_path}/magisk --post-fs-data\n"
        "\n"
        "on property:vold.decrypt=trigger_restart_framework\n"
        f"    exec u:r:magisk:s0 0 0 -- {tmp_path}/magisk --service\n"
        "\n"
        "on nonencrypted\n"
        f"    exec u:r:magisk:s0 0 0 -- {tmp_path}/magisk --service\n"
        "\n"
        "on property:sys.boot_completed=1\n"
        f"    exec u:r:magisk:s0 0 0 -- {tmp_path}/magisk --boot-complete\n"
    )
    out += magisk_rc
    return out


def verify_effective_init_rc(content: str, *, keep_legacy_io=False):
    """Validate that the effective script contains required hooks and clean syntax."""
    if "retain-vegas26-v2.sh" not in content:
        raise ValueError("Effective init.rc is missing retain-vegas26-v2.sh hook")
    if "service vegas26_top_app_watch" not in content:
        raise ValueError("Effective init.rc is missing vegas26_top_app_watch service")
    if "magisk --post-fs-data" not in content or "magisk --boot-complete" not in content:
        raise ValueError("Effective init.rc is missing Magisk lifecycle actions")
    legacy_paths = ["/dev/cpuctl", "/dev/cpuset", "/dev/memcg"]
    if not keep_legacy_io:
        legacy_paths.append("/dev/blkio")
    for legacy in legacy_paths:
        if legacy in content:
            raise ValueError(f"Effective init.rc contains legacy cgroup path: {legacy}")


def retention_script(files, init_body, *, keep_legacy_io=False, io_canary=False):
    if keep_legacy_io:
        controller_guard = """/system/bin/awk '$1 == "cpu" && $2 == 0 {cpu = 1} $1 == "cpuset" && $2 == 0 {cpuset = 1} $1 == "blkio" && $2 > 0 {io = 1} END {exit !(cpu && cpuset && io)}' /proc/cgroups"""
    elif io_canary:
        controller_guard = """if "$toybox" grep -q ' - cgroup ' /proc/1/mountinfo; then exit 1; fi
for controller in cpu cpuset io memory pids; do
    "$toybox" grep -qw "$controller" /sys/fs/cgroup/cgroup.subtree_control || exit 1
done"""
    else:
        controller_guard = """grep -Eq '(^| )cgroup_no_v1=all,named( |$)' /proc/cmdline"""
    lines = [
        "#!/system/bin/sh",
        "set -eu",
        "toybox=/system/bin/toybox",
        "mounted=''",
        "phase=controllers",
        "exec >/dev/vegas26-cgroup-retention.log 2>&1",
        "rollback() {",
        '    status=$?',
        '    printf \'Retention failed at %s (status %s)\\n\' "$phase" "$status"',
        '    for file in $mounted; do "$toybox" umount "$file"; done',
        "}",
        "trap rollback EXIT",
        controller_guard,
        "phase=init-script",
        # Magisk appends its own actions and any other ramdisk scripts.
        f'init_hash=$("$toybox" head -c {len(init_body)} /{MAIN_INIT} | "$toybox" sha256sum)',
        f'test "${{init_hash%% *}}" = {hashlib.sha256(init_body).hexdigest()}',
    ]
    for name, content in files.items():
        lines.extend((
            f'phase=hash:/{name}',
            f'overlay_hash=$("$toybox" sha256sum /{name})',
            f'test "${{overlay_hash%% *}}" = {hashlib.sha256(content).hexdigest()}',
        ))
    for name, label in LABELS.items():
        lines.extend((
            f'phase=relabel:/{name}',
            f'"$toybox" chcon u:object_r:{label}:s0 /{name}',
            f'phase=bind:/{name}',
            f'"$toybox" mount -o bind /{name} /{name}',
            f'mounted="/{name} $mounted"',
        ))
    lines.extend((
        'phase=power-bridge',
        '/system/bin/sh "$1/run-vegas26-top-app-bridge.sh" --prepare',
        'printf \'Retention succeeded\\n\'',
        "trap - EXIT",
    ))
    return "\n".join(line.rstrip() for line in lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("firmware_library", type=Path)
    parser.add_argument("candidate_library", type=Path)
    parser.add_argument("staging", type=Path, help="New private output directory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--keep-legacy-io", action="store_true",
                      help="Verify the CPU and cpuset canary's intentional blkio v1 mount")
    mode.add_argument("--io-canary", action="store_true",
                      help="Require all five v2 controllers on the diagnostic kernel")
    args = parser.parse_args()

    scripts = Path(__file__).resolve().parent
    subprocess.run(
        [sys.executable, str(scripts / "verify-libprocessgroup-abi.py"),
         str(args.firmware_library), str(args.candidate_library)],
        check=True,
    )
    library = args.candidate_library.read_bytes()
    if b"vegas26-sched" not in library:
        parser.error("The candidate lacks the vegas26 threaded scheduling changes")

    raw_init = (args.policy / MAIN_INIT).read_text(encoding="utf-8")
    if not raw_init.endswith("\n"):
        raw_init += "\n"
    effective_init = transform_effective_init_rc(raw_init, INIT)
    verify_effective_init_rc(effective_init, keep_legacy_io=args.keep_legacy_io)
    init_body = transform_init_body(raw_init).encode("utf-8")
    files = {name: (args.policy / name).read_bytes() for name in LABELS
             if name not in (MAIN_INIT, LIBRARY)}
    files[LIBRARY] = library
    overlay = args.staging / "overlay.d"
    args.staging.mkdir(mode=0o700)
    (args.staging / "effective-init.rc").write_text(effective_init, encoding="utf-8", newline="\n")
    for name, content in files.items():
        path = overlay / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (overlay / "vegas26-unified.rc").write_text(INIT, encoding="utf-8", newline="\n")
    sbin = overlay / "sbin"
    sbin.mkdir()
    (sbin / INIT_INPUT).write_text(raw_init, encoding="utf-8", newline="\n")
    retention = sbin / "retain-vegas26-v2.sh"
    retention.write_text(
        retention_script(files, init_body, keep_legacy_io=args.keep_legacy_io,
                         io_canary=args.io_canary),
        encoding="utf-8", newline="\n",
    )
    retention.chmod(0o750)
    for name in ("run-vegas26-top-app-bridge.sh", "update-vegas26-top-app-mask.sh"):
        path = sbin / name
        shutil.copyfile(scripts / name, path)
        path.chmod(0o750)
    print(f"Staged {len(files)} firmware overlay files, retention hook and power bridge.")


if __name__ == "__main__":
    main()
