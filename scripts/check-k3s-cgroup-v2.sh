#!/bin/sh
set -eu

fail() {
    printf 'K3s cgroup preflight: %s\n' "$*" >&2
    exit 1
}

mount=/sys/fs/cgroup
runtime=$mount/k3s
test -r /proc/cmdline || fail 'cannot read /proc/cmdline'
grep -Eq '(^| )cgroup_no_v1=all(,named)?( |$)' /proc/cmdline ||
    fail 'kernel command line does not disable v1 controllers'
awk '$0 ~ / - cgroup / { legacy = 1 } END { exit legacy }' /proc/self/mountinfo ||
    fail 'legacy cgroup mount is visible'
awk -v path="$mount" '$5 == path && / - cgroup2 / { found = 1 } END { exit !found }' /proc/self/mountinfo ||
    fail "$mount is not a cgroup2 mount"
awk '
    /^0::/ { unified = 1; next }
    { legacy = 1 }
    END { exit (!unified || legacy) }
' /proc/self/cgroup || fail 'process does not have unified-only membership'

case ${1:-} in
    --host-only) exit 0 ;;
    '') ;;
    *) fail "unknown option: $1" ;;
esac

for parent in "$mount" "$runtime"; do
    test -r "$parent/cgroup.subtree_control" ||
        fail "missing subtree control at $parent"
    for controller in cpu cpuset memory pids io; do
        grep -qw "$controller" "$parent/cgroup.subtree_control" ||
            fail "$controller is not delegated at $parent"
    done
done

test "$(cat "$runtime/cgroup.type")" = domain ||
    fail 'runtime subtree must be a resource domain'
test -w "$runtime/cgroup.subtree_control" ||
    fail 'runtime subtree control is not writable'
for mask in cpus mems; do
    test -n "$(cat "$runtime/cpuset.$mask.effective")" ||
        fail "runtime effective $mask mask is empty"
done
