"""Stage init scripts with the vegas26 legacy memory commands removed."""

import argparse
from pathlib import Path


FILES = {
    "system/etc/init/hw/init.rc": 13,
    "system_ext/etc/init/hw/meta_init.system.rc": 3,
    "vendor/etc/init/hw/factory_init.rc": 3,
}
LEGACY_COMMENTS = {
    "# memory.pressure_level used by lmkd",
    "# app mem cgroups, used by activity manager, lmkd and zygote",
    "# cgroup for system_server and surfaceflinger",
    "# root memory control cgroup, used by lmkd",
}


def migrate(text, expected):
    result = []
    removed = 0
    for line in text.splitlines(keepends=True):
        statement = line.strip()
        if not statement.startswith("#") and "/dev/memcg" in statement:
            if statement.split()[0] not in {"mkdir", "mount", "chmod", "chown", "write"}:
                raise ValueError(f"Unrecognized legacy memory command: {statement}")
            removed += 1
        elif statement not in LEGACY_COMMENTS:
            result.append(line)
    if removed != expected:
        raise ValueError(f"Expected {expected} legacy commands, found {removed}")
    return "".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_policy", type=Path)
    parser.add_argument("staging", type=Path, help="New private output directory")
    args = parser.parse_args()
    staged = {}
    for name, expected in FILES.items():
        try:
            source = (args.firmware_policy / name).read_text(encoding="utf-8")
            staged[name] = migrate(source, expected)
        except (OSError, ValueError) as error:
            parser.exit(1, f"{name}: {error}\n")
    args.staging.mkdir(mode=0o700)
    for name, content in staged.items():
        dest = args.staging / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: removed {FILES[name]} legacy memory commands")


if __name__ == "__main__":
    main()
