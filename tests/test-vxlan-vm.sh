#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
    printf 'Usage: bash tests/test-vxlan-vm.sh <ARM64-Image> <Debian-rootfs.tar.gz> <ARM64-deb-directory> [--bridge-netfilter|--cfs]\n' >&2
    exit 2
fi
image=$(realpath -- "$1")
rootfs=$(realpath -- "$2")
packages=$(realpath -- "$3")
tests_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cpus=1
case ${4:-} in
    '') extra_test=; extra_marker= ;;
    --bridge-netfilter) extra_test=bridge-netfilter-vm.inc; extra_marker=BRIDGE_NETFILTER_PASS ;;
    --cfs) extra_test=cfs-vm.inc; extra_marker=CFS_THROTTLE_PASS; cpus=2 ;;
    *) printf 'Unknown VM test: %s\n' "$4" >&2; exit 2 ;;
esac
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/root"
tar --no-same-owner -xzf "$rootfs" -C "$scratch/root"
for package in "$packages"/*.deb; do
    dpkg-deb -x "$package" "$scratch/root"
done
cat > "$scratch/root/init" <<'EOF'
#!/bin/sh
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
set -eu
mount -t tmpfs tmpfs /dev
mknod /dev/console c 5 1
mknod /dev/null c 1 3
exec </dev/console >/dev/console 2>&1
trap 'echo o > /proc/sysrq-trigger; sleep 10' EXIT
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mkdir -p /run/netns
ip netns add vxpeer
ip link add under0 type veth peer name under1 netns vxpeer
ip addr add 192.0.2.1/30 dev under0
ip link set under0 up
ip -n vxpeer addr add 192.0.2.2/30 dev under1
ip -n vxpeer link set under1 up
ip link add vx0 type vxlan id 43 dev under0 local 192.0.2.1 remote 192.0.2.2 dstport 8472
ip -n vxpeer link add vx1 type vxlan id 43 dev under1 local 192.0.2.2 remote 192.0.2.1 dstport 8472
ip addr add 198.51.100.1/30 dev vx0
ip link set vx0 up
ip -n vxpeer addr add 198.51.100.2/30 dev vx1
ip -n vxpeer link set vx1 up
ping -I vx0 -c 2 -W 3 198.51.100.2
ip netns exec vxpeer ping -I vx1 -c 2 -W 3 198.51.100.1
echo VXLAN_TRAFFIC_PASS
EOF
if [[ -n $extra_test ]]; then
    cat "$tests_dir/$extra_test" >> "$scratch/root/init"
fi
chmod +x "$scratch/root/init"
(cd "$scratch/root" && find . -print0 | cpio --null --quiet -o -H newc | gzip -n > "$scratch/rootfs.gz")
timeout 120s qemu-system-aarch64 -machine virt -cpu cortex-a57 -smp "$cpus" -m 768M \
    -nodefaults -nic none -display none -monitor none -serial stdio -no-reboot \
    -kernel "$image" -initrd "$scratch/rootfs.gz" \
    -append 'console=ttyAMA0 quiet rdinit=/init panic=-1' | tee "$scratch/console.log"
grep -q '^VXLAN_TRAFFIC_PASS' "$scratch/console.log"
if [[ -n $extra_marker ]]; then
    grep -q "^$extra_marker" "$scratch/console.log"
fi
