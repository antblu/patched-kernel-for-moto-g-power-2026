"""Validate the unified vegas26 Android boot without changing device state."""

import argparse
import subprocess


PROBE = r'''
set -eu
fail() { printf '%s\n' "$*" >&2; exit 1; }
test "$(getprop ro.product.device)" = vegas26 || fail 'Unexpected phone model'
test "$(getprop ro.build.id)" = W1WEOS36.48-22-3-3-4-2 || fail 'Unexpected firmware'
test "$(getprop ro.boot.slot_suffix)" = _a || fail 'Unexpected boot slot'
test "$(getprop sys.boot_completed)" = 1 || fail 'Android boot has not completed'
test "$(getenforce)" = Enforcing || fail 'Android SELinux is not enforcing'
grep -Eq '(^| )cgroup_no_v1=all,named( |$)' /proc/cmdline ||
    fail 'Kernel did not boot with cgroup_no_v1=all,named'

awk '/ - cgroup2 / && $5 == "/sys/fs/cgroup" { found=1 } END { exit !found }' /proc/1/mountinfo ||
    fail 'Android init lacks the expected cgroup2 mount'
awk 'NR == 1 && /^0::/ { unified=1 } END { exit !(NR == 1 && unified) }' /proc/1/cgroup ||
    fail 'Android init is not in a unified-only cgroup'
for controller in cpu cpuset memory pids io; do
    grep -qw "$controller" /sys/fs/cgroup/cgroup.controllers ||
        fail "Missing unified controller: $controller"
    grep -qw "$controller" /sys/fs/cgroup/cgroup.subtree_control ||
        fail "Controller is not delegated from the root: $controller"
done

known=' '
checked=' '
count=0
for process in /proc/[0-9]*; do
    namespace=$(readlink "$process/ns/mnt" 2>/dev/null) || continue
    case "$known" in *" $namespace "*) ;; *) known="$known$namespace " ;; esac
    case "$checked" in *" $namespace "*) continue ;; esac
    mounts=$(cat "$process/mountinfo" 2>/dev/null) || continue
    test -n "$mounts" || continue
    case "$mounts" in *" - cgroup "*) fail 'Found a legacy cgroup mount' ;; esac
    checked="$checked$namespace "
    count=$((count + 1))
done

for namespace in $known; do
    case "$checked" in *" $namespace "*) ;; *) fail 'Could not inspect a mount namespace' ;; esac
done
test "$count" -gt 0 || fail 'No mount namespaces inspected'
printf 'PASS unified Android boot, enforcing SELinux, five delegated controllers and %s mount namespaces\n' "$count"
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    args = parser.parse_args()
    result = subprocess.run(
        [args.adb, "shell", "-T", "su -c sh"],
        input=PROBE.encode(),
        timeout=120,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
