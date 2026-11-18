#!/system/bin/sh
# Verified CFS bandwidth throttling test on Moto G Power 2026 hardware
set -eu

cg=/dev/cpuctl/cfs-hardware-test
mkdir -p "$cg"

finish() {
    for p in $(cat "$cg/cgroup.procs" 2>/dev/null || true); do
        kill -9 "$p" 2>/dev/null || true
    done
    rmdir "$cg" 2>/dev/null || true
}
trap finish EXIT

# 10% CPU bandwidth quota: 10,000 us quota per 100,000 us period
echo 100000 > "$cg/cpu.cfs_period_us"
echo 10000 > "$cg/cpu.cfs_quota_us"

# Spawn 2 busy workers pinned to CPU 0 and CPU 1
taskset 1 /system/bin/sh -c 'echo 0 > "$1/cgroup.procs" && while true; do :; done' sh "$cg" &
w1=$!
taskset 2 /system/bin/sh -c 'echo 0 > "$1/cgroup.procs" && while true; do :; done' sh "$cg" &
w2=$!

sleep 2

cat "$cg/cpu.stat"
awk '$1 == "nr_throttled" && $2 > 0 {found=1} END {exit !found}' "$cg/cpu.stat"

kill -9 "$w1" "$w2" 2>/dev/null || true
wait "$w1" "$w2" 2>/dev/null || true

echo CFS_HARDWARE_THROTTLE_PASS
