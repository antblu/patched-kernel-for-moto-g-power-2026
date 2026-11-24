#!/system/bin/sh
set -eu

bb=/data/adb/magisk/busybox
root=/data/adb/debian-trixie
runner=/usr/local/lib/vegas26-k3s
log=/data/adb/tailscaled.log

umask 077
while [ "$(getprop sys.boot_completed)" != 1 ]; do sleep 2; done
[ -x "$root/usr/local/bin/tailscaled" ] || exit 0

if [ -f "$log" ]; then mv -f "$log" "$log.previous"; fi
exec >> "$log" 2>&1

# Apply Android policy routing rules required for tailscaled marked packets and Tailscale subnet
ip rule add priority 5220 fwmark 0x80000/0xff0000 lookup wlan0 2>/dev/null || true
ip rule add priority 97 to 100.64.0.0/10 lookup 52 2>/dev/null || true

# Enter Debian container and supervise tailscaled
exec /system/bin/sh /data/adb/debian-shell --wait-enter \
    /bin/sh "$runner/tailscaled-supervisor.sh"
