#!/system/bin/sh
# Run as root with: adb shell -T 'su -c "unshare -n /system/bin/sh -s"' < tests/test-vxlan-phone.sh
set -eu

namespace=$(readlink /proc/self/ns/net)
if [ "$namespace" = "$(readlink /proc/1/ns/net)" ]; then
    echo 'A private network namespace is required.' >&2
    exit 1
fi

unshare -n sleep 60 &
peer=$!
trap 'kill "$peer" 2>/dev/null || true; wait "$peer" 2>/dev/null || true' EXIT
for attempt in 1 2 3 4 5; do
    peer_namespace=$(readlink "/proc/$peer/ns/net" || true)
    if [ -n "$peer_namespace" ] && [ "$peer_namespace" != "$namespace" ]; then
        break
    fi
    sleep 1
done
test -n "$peer_namespace" && test "$peer_namespace" != "$namespace"

ip link add under0 type veth peer name under1
ip link set under1 netns "$peer"
ip addr add 192.0.2.1/30 dev under0
ip link set under0 up
nsenter -t "$peer" -n ip addr add 192.0.2.2/30 dev under1
nsenter -t "$peer" -n ip link set under1 up
ip link add vx0 type vxlan id 43 dev under0 local 192.0.2.1 remote 192.0.2.2 dstport 8472
nsenter -t "$peer" -n ip link add vx1 type vxlan id 43 dev under1 local 192.0.2.2 remote 192.0.2.1 dstport 8472
ip addr add 198.51.100.1/30 dev vx0
ip link set vx0 up
nsenter -t "$peer" -n ip addr add 198.51.100.2/30 dev vx1
nsenter -t "$peer" -n ip link set vx1 up
ping -I vx0 -c 2 -W 3 198.51.100.2
nsenter -t "$peer" -n -- ping -I vx1 -c 2 -W 3 198.51.100.1
echo VXLAN_TRAFFIC_PASS
