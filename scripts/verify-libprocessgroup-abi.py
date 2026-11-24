"""Check an Android libprocessgroup candidate against the firmware library."""

import argparse
import os
from pathlib import Path
import re
import subprocess


def readelf(path, option):
    return subprocess.check_output(
        ["readelf", "--wide", option, str(path.resolve())],
        env={**os.environ, "LC_ALL": "C"},
        text=True,
    )


def exports(path):
    result = set()
    for line in readelf(path, "--dyn-syms").splitlines():
        columns = line.split()
        if len(columns) < 8 or not re.fullmatch(r"\d+:", columns[0]):
            continue
        _, _, size, kind, binding, visibility, index, name = columns[:8]
        if index != "UND" and binding in {"GLOBAL", "WEAK"} and visibility in {
            "DEFAULT", "PROTECTED"
        }:
            storage_size = size if kind in {"OBJECT", "TLS"} else ""
            result.add((name, kind, binding, visibility, storage_size))
    if not result:
        raise ValueError(f"{path} has no public dynamic exports")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()

    for path in (args.firmware, args.candidate):
        header = readelf(path, "--file-header")
        for expected in (r"Class:\s+ELF64", r"Machine:\s+AArch64", r"Type:\s+DYN"):
            if not re.search(expected, header):
                parser.exit(1, f"Expected an ARM64 ELF shared object: {path}\n")

    stock = exports(args.firmware)
    missing = stock - exports(args.candidate)
    dynamics = [readelf(path, "--dynamic") for path in (args.firmware, args.candidate)]
    dependencies = [set(re.findall(r"\(NEEDED\).*?\[(.*?)\]", value)) for value in dynamics]
    added_dependencies = dependencies[1] - dependencies[0]
    sonames = [re.findall(r"\(SONAME\).*?\[(.*?)\]", value) for value in dynamics]

    for symbol in sorted(missing):
        print("Missing or changed export:", " ".join(symbol).rstrip())
    for dependency in sorted(added_dependencies):
        print("New dependency:", dependency)
    if sonames[0] != sonames[1]:
        print("Changed SONAME:", sonames[0], "->", sonames[1])
    if missing or added_dependencies or sonames[0] != sonames[1]:
        return 1
    print(f"Preserved {len(stock)} public dynamic exports, SONAME and dependency compatibility.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
