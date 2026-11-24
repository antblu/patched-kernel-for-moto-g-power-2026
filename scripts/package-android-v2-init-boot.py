"""Repack the audited vegas26 init_boot backup with a staged v2 Android overlay."""

import argparse
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile


PARTITION_BYTES = 8 * 1024 * 1024
PAGE = 4096
INIT_INPUT = "vegas26-init.rc.in"
OBSOLETE = (
    "overlay.d/vegas26-memory-policy.rc",
    "overlay.d/sbin/retain-memory-policy.sh",
)


def run(tool, *args, directory, capture=False):
    result = subprocess.run([*tool, *args], cwd=directory, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout


def list_ramdisk(cpio, work):
    listing = run(cpio, "ls -r", directory=work, capture=True)
    return {line.rsplit("\t", 1)[-1] for line in listing.splitlines()}


def stage_ramdisk(cpio, work, overlay):
    entries = list_ramdisk(cpio, work)
    commands = [f"rm {name}" for name in OBSOLETE if name in entries]
    files = []
    for path in sorted(overlay.rglob("*")):
        if path.is_symlink() or any(char.isspace() for char in str(path)):
            raise ValueError(f"Unsupported overlay path: {path}")
        entry = "overlay.d/" + path.relative_to(overlay).as_posix()
        if path.is_dir() and entry not in entries:
            commands.append(f"mkdir 0755 {entry}")
        elif path.is_file():
            if entry == f"overlay.d/sbin/{INIT_INPUT}":
                mode = "0600"
            else:
                mode = "0750" if entry.startswith("overlay.d/sbin/") else "0644"
            commands.append(f"add {mode} {entry} {path}")
            files.append((entry, path))
    run(cpio, *commands, directory=work)
    return files


def read_magiskinit(path):
    data = path.read_bytes()
    if len(data) < 64 or not data.startswith(b"\x7fELF\x02\x01") or data[18:20] != b"\xb7\x00":
        raise ValueError("Expected an ARM64 little-endian ELF magiskinit")
    if INIT_INPUT.encode("ascii") not in data:
        raise ValueError("Build magiskinit from v31.1 with the vegas26 init source patch")
    return data


def restore_avb(avbtool, baseline, repacked, output, work):
    info = run(avbtool, "info_image", "--image", str(baseline), directory=work, capture=True)
    if not re.search(r"(?m)^Algorithm:\s+NONE\s*$", info) or not re.search(
        r"(?m)^\s+Partition Name:\s+init_boot\s*$", info
    ):
        raise ValueError("Expected the audited unlocked vegas26 init_boot format")
    salt = re.search(r"(?m)^\s+Salt:\s+([a-f0-9]+)\s*$", info)
    props = re.findall(r"(?m)^    Prop: ([^ ]+) -> '([^']*)'$", info)
    if not salt or len(props) != 3 or repacked[-64:-60] != b"AVBf":
        raise ValueError("Expected the active init_boot AVB footer and build properties")

    length = struct.unpack_from(">Q", repacked, len(repacked) - 52)[0]
    ramdisk_size = struct.unpack_from("<I", repacked, 12)[0]
    if length != (PAGE + ramdisk_size + PAGE - 1) // PAGE * PAGE:
        raise ValueError("Unexpected v4 init_boot payload size")
    output.write_bytes(repacked[:length])
    prop_args = [arg for key, value in props for arg in ("--prop", f"{key}:{value}")]
    run(avbtool, "add_hash_footer", "--image", str(output), "--partition_name", "init_boot",
        "--partition_size", str(PARTITION_BYTES), "--hash_algorithm", "sha256",
        "--salt", salt.group(1), *prop_args, directory=work)
    run(avbtool, "verify_image", "--image", str(output), directory=work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("magiskboot", "avbtool", "active_init_boot", "staging", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--magiskinit", type=Path, required=True,
                        help="ARM64 magiskinit built with patches/magisk31.1-vegas26-init-source.patch")
    args = parser.parse_args()
    baseline = args.active_init_boot.resolve(strict=True)
    overlay = args.staging.resolve(strict=True) / "overlay.d"
    magiskboot = [str(args.magiskboot.resolve(strict=True))]
    avbtool = [sys.executable, str(args.avbtool.resolve(strict=True))]
    if (
        baseline.stat().st_size != PARTITION_BYTES
        or not (overlay / "vegas26-unified.rc").is_file()
        or not (overlay / "sbin" / INIT_INPUT).is_file()
    ):
        parser.error("Expected the 8 MiB baseline and a staged vegas26 overlay")
    if b"vegas26-sched" not in (overlay / "system/lib64/libprocessgroup.so").read_bytes():
        parser.error("Staged overlay lacks the patched library")

    if (overlay / "system/etc/init/hw/init.rc").exists():
        parser.error("Put the cleaned init script in the Magisk policy input")
    effective_rc = (args.staging / "effective-init.rc").read_text(encoding="utf-8")
    if "retain-vegas26-v2.sh" not in effective_rc or "magisk --post-fs-data" not in effective_rc:
        parser.error("Staged overlay lacks effective retention or Magisk actions in init.rc")

    magiskinit = read_magiskinit(args.magiskinit)
    with tempfile.TemporaryDirectory(prefix="vegas26-init-boot-") as temp:
        work = Path(temp)
        run(magiskboot, "unpack", str(baseline), directory=work)
        cpio = [*magiskboot, "cpio", "ramdisk.cpio"]
        (work / "candidate-init").write_bytes(magiskinit)
        run(cpio, "add 0750 init candidate-init", directory=work)
        files = stage_ramdisk(cpio, work, overlay)
        run(magiskboot, "repack", str(baseline), "repacked.img", directory=work)
        # avbtool resolves each hash descriptor against its partition filename.
        verified = work / "init_boot.img"
        restore_avb(avbtool, baseline, (work / "repacked.img").read_bytes(), verified, work)
        run(magiskboot, "unpack", verified.name, directory=work)
        if list_ramdisk(cpio, work).intersection(OBSOLETE):
            raise ValueError("Repacked ramdisk still contains memory-only overlay hooks")
        run(cpio, "extract init checked_init", directory=work)
        if (work / "checked_init").read_bytes() != magiskinit:
            raise ValueError("Repacked ramdisk differs from the supplied magiskinit")
        for entry, source in files:
            run(cpio, f"extract {entry} checked", directory=work)
            if (work / "checked").read_bytes() != source.read_bytes():
                raise ValueError(f"Repacked ramdisk differs at {entry}")
        with args.output.open("xb") as output:
            output.write(verified.read_bytes())
    print(f"Verified and packaged {len(files)} overlay entries and patched magiskinit.")


if __name__ == "__main__":
    main()
