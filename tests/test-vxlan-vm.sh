#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 4 ]]; then
    printf 'Usage: bash tests/test-vxlan-vm.sh <ARM64-Image> <Debian-rootfs.tar.gz> <ARM64-deb-directory> [--bridge-netfilter|--cfs|--unified|--built-in-unified|--k3s-netfilter]\n' >&2
    exit 2
fi
image=$(realpath -- "$1")
rootfs=$(realpath -- "$2")
packages=$(realpath -- "$3")
tests_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cpus=1
boot_args='console=ttyAMA0 quiet rdinit=/init panic=-1'
case ${4:-} in
    '') extra_test=; extra_marker= ;;
    --bridge-netfilter) extra_test=bridge-netfilter-vm.inc; extra_marker=BRIDGE_NETFILTER_PASS ;;
    --k3s-netfilter) extra_test=bridge-netfilter-vm.inc; extra_marker=K3S_PHYSDEV_PASS ;;
    --cfs) extra_test=cfs-vm.inc; extra_marker=ANDROID_WEBVIEW_CGROUP_PLACEMENT_PASS; cpus=2 ;;
    --unified)
        extra_test=cfs-vm.inc; extra_marker=ANDROID_WEBVIEW_CGROUP_PLACEMENT_PASS; cpus=2
        boot_args+=' cgroup_no_v1=all'
        ;;
    --built-in-unified)
        extra_test=cfs-vm.inc; extra_marker=ANDROID_WEBVIEW_CGROUP_PLACEMENT_PASS; cpus=2
        ;;
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
if [[ ${4:-} == --built-in-unified ]]; then
    cp "$tests_dir/../scripts/check-k3s-cgroup-v2.sh" \
        "$tests_dir/../scripts/run-in-k3s-runtime.sh" \
        "$tests_dir/../scripts/update-vegas26-top-app-mask.sh" "$scratch/root/"
    cat >> "$scratch/root/init" <<'EOF'
grep -Eq '(^| )cgroup_no_v1=all,named( |$)' /proc/cmdline
grep -Eq '(^| )rdinit=/init( |$)' /proc/cmdline
mkdir -p /run/legacy-named
if mount -t cgroup -o none,name=k3s-probe none /run/legacy-named; then
    echo 'Named legacy hierarchy mounted during unified-mode test' >&2
    exit 1
fi
awk '$0 ~ / - cgroup / { found=1 } END { exit found }' /proc/self/mountinfo
EOF
fi
if [[ ${4:-} == --unified ]]; then
    cat >> "$scratch/root/init" <<'EOF'
mkdir -p /run/legacy-named
mount -t cgroup -o none,name=k3s-probe none /run/legacy-named
umount /run/legacy-named
echo LEGACY_NAMED_CONTROL_PASS
EOF
fi
if [[ -n $extra_test ]]; then
    cat "$tests_dir/$extra_test" >> "$scratch/root/init"
fi
if [[ ${4:-} == --built-in-unified ]]; then
    cat >> "$scratch/root/init" <<'EOF'
/bin/sh /check-k3s-cgroup-v2.sh
echo K3S_CGROUP_PREFLIGHT_PASS
mkdir -p /dev/cpuset/top-app
printf '1\n' > /dev/cpuset/top-app/cpus
for domain in "$app" "$other"; do
    leaf=$domain/vegas26-sched/background/top-app
    mkdir "$leaf"
    printf 'threaded\n' > "$leaf/cgroup.type"
done
/bin/sh /update-vegas26-top-app-mask.sh
for domain in "$app" "$other"; do
    test "$(cat "$domain/vegas26-sched/background/top-app/cpuset.cpus.effective")" = 1
done
echo VEGAS26_TOP_APP_MASK_PASS
/bin/sh /run-in-k3s-runtime.sh /bin/sh -ec '
    grep -Fxq "0::/runtime/agent" /proc/self/cgroup
    test "$(umask)" = 0022
    if /bin/sh /run-in-k3s-runtime.sh /bin/true; then
        echo "Runtime lock admitted a second agent" >&2
        exit 1
    fi
'
echo K3S_RUNTIME_LAUNCH_PASS
EOF
    extra_marker=K3S_RUNTIME_LAUNCH_PASS
fi
if [[ ${4:-} == --k3s-netfilter ]]; then
    cat >> "$scratch/root/init" <<'EOF'
ip link set lo up
iptables-legacy -A OUTPUT -p icmp -m addrtype --dst-type LOCAL -j DROP
if ping -c 1 -W 2 127.0.0.1; then
    echo 'Address-type filter failed to block local ICMP' >&2
    exit 1
fi
iptables-legacy -D OUTPUT -p icmp -m addrtype --dst-type LOCAL -j DROP
ping -c 1 -W 2 127.0.0.1
echo K3S_ADDRTYPE_PASS
iptables-legacy -A FORWARD -m physdev --physdev-is-bridged -p icmp -j DROP
if ip netns exec brpeer1 ping -c 1 -W 2 198.51.100.10; then
    echo 'Physical bridge match failed to block matching packets' >&2
    exit 1
fi
iptables-legacy -D FORWARD -m physdev --physdev-is-bridged -p icmp -j DROP
ip netns exec brpeer1 ping -c 1 -W 3 198.51.100.10
echo K3S_PHYSDEV_PASS
EOF
fi
chmod +x "$scratch/root/init"
(cd "$scratch/root" && find . -print0 | cpio --null --quiet -o -H newc | gzip -n > "$scratch/rootfs.gz")
timeout 120s qemu-system-aarch64 -machine virt -cpu cortex-a57 -smp "$cpus" -m 768M \
    -nodefaults -nic none -display none -monitor none -serial stdio -no-reboot \
    -kernel "$image" -initrd "$scratch/rootfs.gz" \
    -append "$boot_args" | tee "$scratch/console.log"
grep -q '^VXLAN_TRAFFIC_PASS' "$scratch/console.log"
if [[ -n $extra_marker ]]; then
    grep -q "^$extra_marker" "$scratch/console.log"
fi
