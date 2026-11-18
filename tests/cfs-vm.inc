
mkdir -p /sys/fs/cgroup /run/legacy-blkio
mount -t cgroup -o blkio blkio /run/legacy-blkio
mount -t cgroup2 none /sys/fs/cgroup
if grep -qw io /sys/fs/cgroup/cgroup.controllers; then
    echo 'Block I/O unexpectedly available on the unified hierarchy' >&2
    exit 1
fi
printf '%s\n' '+cpu +cpuset +memory +pids' > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/android /sys/fs/cgroup/runtime
printf '%s\n' '+cpu +cpuset +memory +pids' > /sys/fs/cgroup/runtime/cgroup.subtree_control
limit=/sys/fs/cgroup/runtime/limited
for attempt in 1 2; do
    mkdir "$limit"
    printf '10000 100000\n' > "$limit/cpu.max"
    printf '67108864\n' > "$limit/memory.max"
    printf '32\n' > "$limit/pids.max"
    test -n "$(cat "$limit/cpuset.cpus.effective")"
    workers=
    for cpu in 0 1; do
        taskset -c "$cpu" /bin/sh -c 'printf "0\n" > "$1/cgroup.procs" && exec yes' sh "$limit" >/dev/null &
        workers="$workers $!"
    done
    sleep 2
    for worker in $workers; do
        kill "$worker"
        wait "$worker" || true
    done
    cat "$limit/cpu.stat"
    awk '$1 == "nr_throttled" && $2 > 0 {found=1} END {exit !found}' "$limit/cpu.stat"
    rmdir "$limit"
done
echo CFS_THROTTLE_PASS
