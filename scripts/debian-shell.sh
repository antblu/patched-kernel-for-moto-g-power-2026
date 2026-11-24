#!/system/bin/sh
set -eu

bb=/data/adb/magisk/busybox
root=/data/adb/debian-trixie
pidfile=/data/adb/debian-trixie.init.pid

is_debian_init() {
    case "$1" in ''|*[!0-9]*) return 1 ;; esac
    expected=$("$bb" stat -L -c '%d:%i' "$root/usr/bin/tini") || return 1
    actual=$("$bb" stat -L -c '%d:%i' "/proc/$1/exe" 2>/dev/null) || return 1
    [ "$actual" = "$expected" ]
}

wait_for_init() {
    attempts=0
    while [ "$attempts" -lt 60 ]; do
        pid=$(cat "$pidfile" 2>/dev/null) || pid=
        if is_debian_init "$pid"; then return 0; fi
        attempts=$((attempts + 1))
        sleep 2
    done
    printf 'Timed out waiting for the Debian boot instance.\n' >&2
    return 1
}

if [ "${1:-}" = --boot ]; then
    exec "$bb" unshare -m -p -f -i -u /system/bin/sh "$0" --init
fi
if [ "${1:-}" = --wait-enter ]; then
    shift
    wait_for_init
    set -- --enter "$@"
fi
if [ "${1:-}" = --enter ]; then
    shift
    pid=$(cat "$pidfile")
    is_debian_init "$pid"
    if [ "$#" -eq 0 ]; then set -- /bin/bash -l; fi
    exec "$bb" nsenter -t "$pid" -m -p -i -u -r -w /usr/bin/env -i \
        HOME=/root TERM="${TERM:-xterm}" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
fi
if [ "${1:-}" != --inside ] && [ "${1:-}" != --init ]; then
    exec "$bb" unshare -m -p -f -i -u /system/bin/sh "$0" --inside "$@"
fi
mode=$1
shift

test "$("$bb" readlink /proc/self/ns/mnt)" != "$("$bb" readlink /proc/1/ns/mnt)"
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
"$bb" mkdir -p "$root/dev/net"
if [ -e /dev/net/tun ]; then
    : > "$root/dev/net/tun"
    "$bb" mount --bind /dev/net/tun "$root/dev/net/tun"
else
    "$bb" mknod "$root/dev/net/tun" c 10 200
    "$bb" chmod 666 "$root/dev/net/tun"
fi
"$bb" mount -t tmpfs -o nosuid,nodev,mode=755 tmpfs "$root/run"

"$bb" mkdir -p "$root/sys/fs/cgroup"
# A v1 mount can claim a controller globally, even in a private mount namespace.
"$bb" mount --bind /sys/fs/cgroup "$root/sys/fs/cgroup"

"$bb" mkdir -p "$root/sys/fs/bpf"
if [ -d /sys/fs/bpf ]; then
    "$bb" mount --bind /sys/fs/bpf "$root/sys/fs/bpf"
fi

if [ "$#" -eq 0 ]; then
    set -- /bin/bash -l
fi
if [ "$mode" = --init ]; then
    # OCI exec joins the mount namespace and takes that namespace's root.
    # Move Debian onto / before chroot so a later pivot_root replaces that root.
    cd "$root"
    "$bb" mount --move . /
    root=.
fi
exec "$bb" chroot "$root" /usr/bin/env -i \
    HOME=/root TERM="${TERM:-xterm}" PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "$@"
