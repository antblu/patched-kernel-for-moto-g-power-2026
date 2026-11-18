#!/system/bin/sh
set -eu

bb=/data/adb/magisk/busybox
root=/data/adb/debian-trixie
pidfile=/data/adb/debian-trixie.init.pid

if [ "${1:-}" = --boot ]; then
    exec "$bb" unshare -m -p -f -i -u /system/bin/sh "$0" --init
fi
if [ "${1:-}" = --enter ]; then
    shift
    pid=$(cat "$pidfile")
    case "$pid" in ''|*[!0-9]*) exit 1 ;; esac
    [ "$("$bb" readlink "/proc/$pid/exe")" = "$root/usr/bin/tini" ]
    if [ "$#" -eq 0 ]; then set -- /bin/bash -l; fi
    exec "$bb" nsenter -t "$pid" -m -p -i -u -r -w /usr/bin/env -i \
        HOME=/root TERM="${TERM:-xterm}" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
fi
if [ "${1:-}" != --inside ] && [ "${1:-}" != --init ]; then
    exec "$bb" unshare -m -p -f -i -u /system/bin/sh "$0" --inside "$@"
fi
mode=$1
shift

"$bb" mount --make-rprivate /
"$bb" mount --bind "$root" "$root"
if [ "$mode" = --init ]; then
    # Read the outer PID before overmounting proc inside the chroot.
    while read -r field outer inner; do
        [ "$field" = NSpid: ] || continue
        [ "$inner" = 1 ]
        umask 077
        printf '%s\n' "$outer" > "$pidfile"
        break
    done < /proc/self/status
    set -- /usr/bin/tini -- /bin/sleep infinity
fi
"$bb" mount -t proc -o nosuid,nodev,noexec proc "$root/proc"
"$bb" mount -t sysfs -o nosuid,nodev,noexec sysfs "$root/sys"
"$bb" mount -t tmpfs -o nosuid,mode=755 tmpfs "$root/dev"
"$bb" mkdir "$root/dev/pts" "$root/dev/shm"
"$bb" chmod 1777 "$root/dev/shm"
"$bb" mount -t devpts -o newinstance,ptmxmode=0666,mode=0620 devpts "$root/dev/pts"
"$bb" ln -s pts/ptmx "$root/dev/ptmx"
"$bb" ln -s /proc/self/fd "$root/dev/fd"
for device in null zero full random urandom tty kmsg; do
    : > "$root/dev/$device"
    "$bb" mount --bind "/dev/$device" "$root/dev/$device"
done
"$bb" mount -t tmpfs -o nosuid,nodev,mode=755 tmpfs "$root/run"

"$bb" mkdir -p "$root/sys/fs/cgroup"
"$bb" mount -t tmpfs -o mode=755 cgroup_root "$root/sys/fs/cgroup"
for ctrl in cpu cpuacct cpuset memory blkio pids freezer; do
    "$bb" mkdir -p "$root/sys/fs/cgroup/$ctrl"
    "$bb" mount -t cgroup -o "$ctrl" none "$root/sys/fs/cgroup/$ctrl" || true
done
"$bb" mkdir -p "$root/sys/fs/cgroup/unified"
"$bb" mount -t cgroup2 none "$root/sys/fs/cgroup/unified" || true

if [ "$#" -eq 0 ]; then
    set -- /bin/bash -l
fi
exec "$bb" chroot "$root" /usr/bin/env -i \
    HOME=/root TERM="${TERM:-xterm}" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
