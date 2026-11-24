"""Stage the vegas26 unified controller and I/O task profile definitions."""

import argparse
import json
from pathlib import Path


LEGACY = {"cpu", "cpuset", "blkio"}
IO_WEIGHTS = {
    "LowIoPriority": "10",
    "NormalIoPriority": "100",
    "HighIoPriority": "100",
    "MaxIoPriority": "100",
}
SCHEDULER_INIT_FILES = {
    "system/etc/init/hw/init.rc": 175,
    "product/etc/init/init.mmi.product.rc": 8,
    "vendor/etc/init/hw/init.cgroup.rc": 30,
    "vendor/etc/init/hw/init.mt6835.rc": 5,
    "vendor/etc/init/vendor.mediatek.hardware.mtkpower@1.0-init.rc": 46,
}
LEGACY_PATHS = ("/dev/cpuctl", "/dev/cpuset", "/dev/blkio")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def migrate_descriptors(policy, *, keep_legacy_io=False):
    entries = policy["Cgroups"]
    if {entry["Controller"] for entry in entries} != LEGACY:
        raise ValueError("Unexpected legacy controller definitions")
    policy["Cgroups"] = [
        entry for entry in entries if keep_legacy_io and entry["Controller"] == "blkio"
    ]
    v2 = policy["Cgroups2"]
    if v2["Path"] != "/sys/fs/cgroup":
        raise ValueError("Unexpected unified hierarchy path")
    existing = {entry["Controller"] for entry in v2["Controllers"]}
    if existing & {"cpu", "cpuset", "io"}:
        raise ValueError("Controller already exists in unified policy")
    v2["Controllers"].extend(
        {"Controller": controller, "Path": ".", "NeedsActivation": True, "MaxActivationDepth": 3}
        for controller in (("cpu", "cpuset") if keep_legacy_io else ("cpu", "cpuset", "io"))
    )
    return policy


def migrate_io_profiles(policy):
    attributes = policy["Attributes"]
    if any(entry["Name"] in {"BfqWeight", "IoPriorityClass"} for entry in attributes):
        raise ValueError("Unified I/O attributes are already defined")
    attributes[:] = [entry for entry in attributes if entry["Name"] != "MemSwappiness"]
    attributes.append({"Name": "BfqWeight", "Controller": "io", "File": "io.bfq.weight"})
    attributes.append({"Name": "IoPriorityClass", "Controller": "io", "File": "io.prio.class"})
    migrated = set()
    for profile in policy["Profiles"]:
        name = profile["Name"]
        actions = []
        for action in profile["Actions"]:
            params = action["Params"]
            if action["Name"] == "SetAttribute" and params.get("Name") == "MemSwappiness":
                continue
            if action["Name"] == "JoinCgroup" and params.get("Controller") == "blkio":
                expected = "background" if name == "LowIoPriority" else ""
                if name not in IO_WEIGHTS or params["Path"] != expected or name in migrated:
                    raise ValueError(f"Unexpected legacy I/O action in {name}")
                action = {
                    "Name": "SetAttribute",
                    "Params": {"Name": "BfqWeight", "Value": IO_WEIGHTS[name]},
                }
                actions.append(action)
                action = {
                    "Name": "SetAttribute",
                    "Params": {
                        "Name": "IoPriorityClass",
                        "Value": "restrict-to-be" if name == "LowIoPriority" else "no-change",
                    },
                }
                migrated.add(name)
            actions.append(action)
        profile["Actions"] = actions
    if migrated != IO_WEIGHTS.keys():
        raise ValueError("Missing legacy I/O profiles")
    return policy


def migrate_scheduler_init(source, expected, *, keep_legacy_io=False):
    kept = []
    removed = 0
    for line in source.splitlines(keepends=True):
        tokens = line.split()
        if (tokens and not tokens[0].startswith("#")
                and any(token == path or token.startswith(path + "/")
                        for token in tokens[1:] for path in LEGACY_PATHS)):
            if tokens[0] not in {"mkdir", "chmod", "chown", "write", "copy"}:
                raise ValueError(f"Unhandled legacy scheduler command: {line.strip()}")
            removed += 1
            if keep_legacy_io and any(token == "/dev/blkio" or token.startswith("/dev/blkio/")
                                      for token in tokens[1:]):
                kept.append(line)
        else:
            kept.append(line)
    if removed != expected:
        raise ValueError(f"Expected {expected} legacy scheduler commands, found {removed}")
    return "".join(kept)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_policy", type=Path)
    parser.add_argument("memory_canary", type=Path)
    parser.add_argument("staging", type=Path)
    parser.add_argument("--keep-legacy-io", action="store_true",
                        help="Stage a CPU and cpuset canary with the existing blkio policy")
    parser.add_argument(
        "--memory-init-stage", type=Path,
        help="Also stage init scripts using the output of prepare-android-memory-v2.py",
    )
    args = parser.parse_args()
    try:
        system_profiles = read_json(args.firmware_policy / "system/etc/task_profiles.json")
        vendor_profiles = read_json(args.memory_canary / "task_profiles.json")
        policies = {
            "system/etc/cgroups.json": migrate_descriptors(
                read_json(args.firmware_policy / "system/etc/cgroups.json"),
                keep_legacy_io=args.keep_legacy_io,
            ),
            "vendor/etc/cgroups.json": migrate_descriptors(
                read_json(args.memory_canary / "cgroups.json"),
                keep_legacy_io=args.keep_legacy_io,
            ),
            "system/etc/task_profiles.json": (
                system_profiles if args.keep_legacy_io else migrate_io_profiles(system_profiles)
            ),
            "vendor/etc/task_profiles.json": (
                vendor_profiles if args.keep_legacy_io else migrate_io_profiles(vendor_profiles)
            ),
        }
        files = {name: json.dumps(policy, indent=2) + "\n" for name, policy in policies.items()}
        if args.memory_init_stage:
            for path in args.memory_init_stage.rglob("*.rc"):
                files[path.relative_to(args.memory_init_stage).as_posix()] = path.read_text(
                    encoding="utf-8"
                )
            if "system/etc/init/hw/init.rc" not in files:
                raise ValueError("Memory init stage is missing system init.rc")
            for name, expected in SCHEDULER_INIT_FILES.items():
                source = files.get(name)
                if source is None:
                    source = (args.firmware_policy / name).read_text(encoding="utf-8")
                files[name] = migrate_scheduler_init(source, expected, keep_legacy_io=args.keep_legacy_io)
            product_init = "product/etc/init/init.mmi.product.rc"
            stock_swap = "setprop ro.config.moto_swap_supported true"
            if files[product_init].count(stock_swap) != 1:
                raise ValueError("Unexpected Motorola swap setting")
            files[product_init] = files[product_init].replace(
                stock_swap, "setprop ro.config.moto_swap_supported false"
            )
    except (KeyError, OSError, ValueError) as error:
        parser.exit(1, f"Policy input does not match the vegas26 baseline: {error}\n")

    args.staging.mkdir(mode=0o700)
    for name, content in files.items():
        dest = args.staging / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8", newline="\n")
        print(f"Staged {name}")


if __name__ == "__main__":
    main()
