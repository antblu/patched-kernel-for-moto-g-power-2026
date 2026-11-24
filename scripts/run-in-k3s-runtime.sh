#!/bin/sh
set -eu

if [ "$#" -eq 0 ]; then
    printf 'Usage: %s COMMAND [ARG ...]\n' "$0" >&2
    exit 2
fi

scripts=$(dirname -- "$0")
check=$scripts/check-k3s-cgroup-v2.sh
sh "$check" --host-only
if [ -d /sys/fs/bpf/netd_shared ]; then
    identity=$(stat -Lc '%d:%i' /)
    namespace_identity=$(nsenter --mount=/proc/self/ns/mnt -- /usr/bin/stat -Lc '%d:%i' /)
    if [ "$identity" != "$namespace_identity" ]; then
        printf 'K3s needs Debian as the mount namespace root. Restart Debian with the updated launcher.\n' >&2
        exit 1
    fi
fi
lock=/run/vegas26-k3s-agent.lock
(umask 077; : >> "$lock")
exec 9>>"$lock"
flock -n 9 || {
    printf 'A K3s agent already holds the Debian runtime lock.\n' >&2
    exit 1
}

# The namespace root check above keeps propagation changes inside Debian.
if [ -d /sys/fs/bpf/netd_shared ]; then
    mount --make-rshared /
fi

root=/sys/fs/cgroup
runtime=$root/k3s
# Kubelet creates directories for non-root workloads and projected volumes.
umask 022
sh "$scripts/setup-k3s-cgroup.sh"
sh "$check"

mkdir -p "$runtime/agent"
printf '%s\n' "$$" > "$runtime/agent/cgroup.procs"
# Keep the lock in the supervising shell so orphaned shims cannot block a retry.
"$@" 9>&- &
child=$!
terminate() {
    kill -TERM "$child" 2>/dev/null || :
    wait "$child" || :
    exit 143
}
trap terminate HUP INT TERM
wait "$child"
