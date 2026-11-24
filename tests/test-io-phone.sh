#!/usr/bin/env bash
# Verified cgroup v2 I/O accounting and proportional behavior probe on vegas26
set -euo pipefail

scratch=$(mktemp -d /var/tmp/vegas26-io-probe.XXXXXXXX)
cg_fg=/sys/fs/cgroup/${scratch##*/}-fg
cg_bg=/sys/fs/cgroup/${scratch##*/}-bg

cleanup() {
    rmdir "$cg_fg" "$cg_bg" 2>/dev/null || true
    rm -rf -- "$scratch"
}
trap cleanup EXIT

mapped=$(findmnt --raw --noheadings --target "$scratch" --output MAJ:MIN)
slaves=(/sys/dev/block/"$mapped"/slaves/*)
[[ ${#slaves[@]} == 1 && -e ${slaves[0]} ]] || {
    echo "Expected the probe files to be on a single-device mapper volume" >&2
    exit 1
}
device=$(readlink -f "${slaves[0]}")
if [[ -f $device/partition ]]; then device=${device%/*}; fi
physical=$(cat "$device/dev")
printf 'Accounting devices: mapper=%s physical=%s\n' "$mapped" "$physical"

wbytes() {
    awk -v device="$2" '$1 == device {
        for (i = 2; i <= NF; i++) {
            if ($i ~ /^wbytes=/) {
                split($i, field, "=")
                print field[2]
            }
        }
    }' "$1/io.stat"
}

run_round() {
    local mode="$1"
    local round="$2"
    local fg_weight="$3"
    local bg_weight="$4"
    local bytes_mb=96
    # Each trial starts with new cgroups so io.stat contains only that trial.
    mkdir "$cg_fg" "$cg_bg"

    echo "$fg_weight" > "$cg_fg/io.bfq.weight"
    echo "$fg_weight" > "$cg_fg/io.weight"
    echo "$bg_weight" > "$cg_bg/io.bfq.weight"
    echo "$bg_weight" > "$cg_bg/io.weight"

    rm -f "$scratch/fg.dat" "$scratch/bg.dat" "$scratch/fg.time" "$scratch/bg.time"

    # Launch background writer
    (
        echo 0 > "$cg_bg/cgroup.procs"
        t_start=$(date +%s%N)
        dd if=/dev/zero of="$scratch/bg.dat" bs=1M count="$bytes_mb" oflag=direct status=none
        t_end=$(date +%s%N)
        echo "$t_start $t_end" > "$scratch/bg.time"
    ) &
    pid_bg=$!

    # Launch foreground writer
    (
        echo 0 > "$cg_fg/cgroup.procs"
        t_start=$(date +%s%N)
        dd if=/dev/zero of="$scratch/fg.dat" bs=1M count="$bytes_mb" oflag=direct status=none
        t_end=$(date +%s%N)
        echo "$t_start $t_end" > "$scratch/fg.time"
    ) &
    pid_fg=$!

    local status=0
    wait "$pid_fg" || status=$?
    wait "$pid_bg" || status=$?
    [[ $status == 0 ]]

    read -r fg_start fg_end < "$scratch/fg.time"
    read -r bg_start bg_end < "$scratch/bg.time"

    local fg_lat_ms=$(( (fg_end - fg_start) / 1000000 ))
    local bg_lat_ms=$(( (bg_end - bg_start) / 1000000 ))

    # Confirm overlap: start of either is before end of the other
    local overlap="NO"
    if [ "$fg_start" -le "$bg_end" ] && [ "$bg_start" -le "$fg_end" ]; then
        overlap="YES"
    fi

    local fg_wbytes_dm fg_wbytes_sdc bg_wbytes_dm bg_wbytes_sdc
    fg_wbytes_dm=$(wbytes "$cg_fg" "$mapped")
    fg_wbytes_sdc=$(wbytes "$cg_fg" "$physical")
    bg_wbytes_dm=$(wbytes "$cg_bg" "$mapped")
    bg_wbytes_sdc=$(wbytes "$cg_bg" "$physical")

    printf "MODE=%-6s ROUND=%d OVERLAP=%-3s FG_WEIGHT=%-3s BG_WEIGHT=%-3s FG_LAT_MS=%-4d BG_LAT_MS=%-4d FG_DM_BYTES=%s FG_SDC_BYTES=%s BG_DM_BYTES=%s BG_SDC_BYTES=%s\n" \
        "$mode" "$round" "$overlap" "$fg_weight" "$bg_weight" "$fg_lat_ms" "$bg_lat_ms" \
        "${fg_wbytes_dm:-0}" "${fg_wbytes_sdc:-0}" "${bg_wbytes_dm:-0}" "${bg_wbytes_sdc:-0}"
    local bytes value
    bytes=$((bytes_mb * 1024 * 1024))
    [[ $overlap == YES ]] || { echo 'Writers did not overlap' >&2; return 1; }
    for value in "$fg_wbytes_dm" "$fg_wbytes_sdc" "$bg_wbytes_dm" "$bg_wbytes_sdc"; do
        [[ ${value:-0} -ge $bytes ]] || { echo 'Incomplete cgroup write accounting' >&2; return 1; }
    done
    rmdir "$cg_fg" "$cg_bg"
}

echo "=== EQUAL-WEIGHT TRIALS (100:100) ==="
for r in 1 2 3; do
    run_round "EQUAL" "$r" 100 100
    sleep 1
done

echo "=== DIFFERENTIATED TRIALS (100:10) ==="
for r in 1 2 3; do
    run_round "100:10" "$r" 100 10
    sleep 1
done
