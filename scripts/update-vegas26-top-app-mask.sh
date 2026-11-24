#!/system/bin/sh
set -eu

root=/sys/fs/cgroup
source=/dev/cpuset/top-app/cpus
busybox=/data/adb/magisk/busybox

update_scheduler() (
    exec 9<"$1"
    if [ -x "$busybox" ]; then
        "$busybox" flock -x 9
    else
        flock -x 9
    fi

    IFS= read -r mask < "$source" || [ -n "${mask:-}" ]
    case "$mask" in
        ''|*[!0-7,-]*)
            printf 'Invalid vegas26 top-app CPU mask\n' >&2
            exit 1
            ;;
    esac

    result=0
    for target in "$1"/*/top-app/cpuset.cpus; do
        [ -f "$target" ] || continue
        if ! printf '%s\n' "$mask" > "$target" && [ -f "$target" ]; then
            result=1
        fi
    done
    exit "$result"
)

status=0
for base in "$root" "$root/apps" "$root/system"; do
    for scheduler in "$base"/uid_*/pid_*/vegas26-sched; do
        [ -d "$scheduler" ] || continue
        if ! update_scheduler "$scheduler" && [ -d "$scheduler" ]; then
            status=1
        fi
    done
done
exit "$status"
