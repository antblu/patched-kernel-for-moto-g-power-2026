#!/system/bin/sh
set -eu

root=/data/adb/debian-trixie
runner=/usr/local/lib/vegas26-k3s
config=/etc/rancher/k3s/vegas26-lab/config.yaml
log=/data/adb/vegas26-k3s.log

umask 077
while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 2; done
test -f "$root$config"
[ ! -e "$root${config%/*}/disabled" ] || exit 0
if [ -f "$log" ]; then mv -f "$log" "$log.previous"; fi
exec >> "$log" 2>&1
if [ "$(getenforce)" = Enforcing ]; then
    setenforce 0
fi
test "$(getenforce)" = Permissive
exec /system/bin/sh /data/adb/debian-shell --wait-enter \
    /bin/sh "$runner/k3s-supervisor.sh" "$config"
