#!/system/bin/sh
set -eu

mask=/dev/cpuset/top-app/cpus
/system/bin/awk '$1 == "cpuset" && $2 == 0 && $4 == 1 {found = 1}
    END {exit !found}' /proc/cgroups
/system/bin/toybox grep -qw cpuset /sys/fs/cgroup/cgroup.controllers

case ${1:-} in
    --prepare)
        mkdir -p /dev/cpuset/top-app
        chmod 0755 /dev/cpuset /dev/cpuset/top-app
        if [ ! -e "$mask" ]; then
            printf '%s\n' 0-7 > "$mask"
        fi
        chown system:system "$mask"
        chmod 0660 "$mask"
        /system/bin/toybox chcon u:object_r:cgroup:s0 /dev/cpuset /dev/cpuset/top-app "$mask"
        ;;
    --watch)
        handler=$2
        test -x "$handler"
        "$handler"
        exec /data/adb/magisk/busybox inotifyd "$handler" "$mask:w"
        ;;
    *)
        printf 'Usage: %s --prepare | --watch MASK_HANDLER\n' "$0" >&2
        exit 2
        ;;
esac
