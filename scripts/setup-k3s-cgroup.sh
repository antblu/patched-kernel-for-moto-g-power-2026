#!/system/bin/sh
set -eu

root=/sys/fs/cgroup
subtree=$root/k3s

case ${1:-} in
    --rollback)
        [ ! -d "$subtree" ] || rmdir "$subtree"
        exit
        ;;
    '') ;;
    *) printf 'Usage: %s [--rollback]\n' "$0" >&2; exit 2 ;;
esac

fail() {
    printf 'K3s cgroup setup: %s\n' "$*" >&2
    exit 1
}

grep -Eq '(^| )cgroup_no_v1=all(,named)?( |$)' /proc/cmdline ||
    fail 'kernel does not disable v1 controllers'
awk '$0 ~ / - cgroup / { legacy = 1 } END { exit legacy }' /proc/1/mountinfo ||
    fail 'PID 1 sees a legacy cgroup mount'
awk -v path="$root" '$5 == path && / - cgroup2 / { found = 1 } END { exit !found }' /proc/self/mountinfo ||
    fail "$root is not cgroup2"

available=$(cat "$root/cgroup.controllers")
enabled=$(cat "$root/cgroup.subtree_control")
controllers=
for controller in cpu cpuset memory pids io; do
    if printf '%s\n' "$available" | grep -qw "$controller"; then
        printf '%s\n' "$enabled" | grep -qw "$controller" ||
            fail "$controller is available but Android has not enabled it at the root"
        controllers="${controllers:+$controllers }+$controller"
    fi
done
test -n "$controllers" || fail 'no requested controllers available'

mkdir -p "$subtree"
test "$(cat "$subtree/cgroup.type")" = domain || fail "$subtree is not a domain"
test -z "$(cat "$subtree/cgroup.procs")" || fail "$subtree contains internal processes"
printf '%s\n' "$controllers" > "$subtree/cgroup.subtree_control"
