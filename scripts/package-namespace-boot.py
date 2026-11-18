"""Package the audited ARM64 Image using the matching stock v4 boot header."""

import argparse
import gzip
import hashlib
import struct
from pathlib import Path

PAGE = 4096
BOOT_BYTES = 64 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_boot", type=Path)
    parser.add_argument("build_output", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    image = (args.build_output / "arch/arm64/boot/Image").read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    manifest = (args.build_output / "build-manifest.txt").read_text().splitlines()
    supported_profiles = {
        "profile=experimental-namespaces",
        "profile=experimental-namespaces-pids",
        "profile=experimental-namespaces-pids-vxlan",
        "profile=experimental-namespaces-pids-vxlan-bridge",
        "profile=experimental-namespaces-pids-vxlan-cfs",
    }
    if (f"{digest}  arch/arm64/boot/Image" not in manifest or
            supported_profiles.isdisjoint(manifest) or image[56:60] != b"ARM\x64"):
        parser.error("Expected a manifest-verified namespace build.")
    with args.stock_boot.open("rb") as stock:
        header = bytearray(stock.read(PAGE))
    if (args.stock_boot.stat().st_size != BOOT_BYTES or len(header) != PAGE or
            header[:8] != b"ANDROID!" or struct.unpack_from("<I", header, 40)[0] != 4 or
            struct.unpack_from("<I", header, 12)[0] or struct.unpack_from("<I", header, 1580)[0]):
        parser.error("Expected the matching stock v4 partition without an embedded ramdisk.")

    payload = gzip.compress(image, mtime=0)
    padding = bytes(-len(payload) % PAGE)
    if PAGE + len(payload) + len(padding) > BOOT_BYTES:
        parser.error("The candidate exceeds the boot partition size.")
    struct.pack_into("<I", header, 8, len(payload))
    with args.output.open("xb") as output:
        output.write(header)
        output.write(payload)
        output.write(padding)
    print("Wrote unsigned v4 image. Keep the image private and verify rollback before flashing.")


if __name__ == "__main__":
    main()
