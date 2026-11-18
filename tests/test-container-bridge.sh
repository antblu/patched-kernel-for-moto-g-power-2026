#!/system/bin/sh
# Verified container bridge networking probe for Moto G Power 2026
set -eu

ip link del veth-ct1-br 2>/dev/null || true
ip link del veth-ct2-br 2>/dev/null || true
ip link del br-test0 2>/dev/null || true
ip rule del pref 9999 2>/dev/null || true

# Add routing rule for table main (Android Netd omits it by default)
ip rule add from all lookup main pref 9999
echo 1 > /proc/sys/net/ipv4/ip_forward

# 1. Create bridge
ip link add name br-test0 type bridge
ip addr add 172.20.0.1/24 dev br-test0
ip link set br-test0 up

# Whitelist bridge on host iptables
iptables -I INPUT 1 -i br-test0 -j ACCEPT
iptables -I FORWARD 1 -i br-test0 -j ACCEPT
iptables -I FORWARD 1 -o br-test0 -j ACCEPT

# 2. Spawn two background sleep processes in isolated network namespaces
unshare -n sleep 120 &
pid1=$!
unshare -n sleep 120 &
pid2=$!

finish() {
    kill "$pid1" "$pid2" 2>/dev/null || true
    wait "$pid1" "$pid2" 2>/dev/null || true
    iptables -D INPUT -i br-test0 -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -i br-test0 -j ACCEPT 2>/dev/null || true
    iptables -D FORWARD -o br-test0 -j ACCEPT 2>/dev/null || true
    ip rule del pref 9999 2>/dev/null || true
    ip link del veth-ct1-br 2>/dev/null || true
    ip link del veth-ct2-br 2>/dev/null || true
    ip link del br-test0 2>/dev/null || true
}
trap finish EXIT

# 3. Create veth pairs and assign to namespaces
ip link add veth-ct1 type veth peer name veth-ct1-br
ip link set veth-ct1 netns "$pid1"
ip link set veth-ct1-br master br-test0
ip link set veth-ct1-br up

ip link add veth-ct2 type veth peer name veth-ct2-br
ip link set veth-ct2 netns "$pid2"
ip link set veth-ct2-br master br-test0
ip link set veth-ct2-br up

# 4. Configure interfaces in containers
nsenter -t "$pid1" -n -- ip link set lo up
nsenter -t "$pid1" -n -- ip addr add 172.20.0.2/24 dev veth-ct1
nsenter -t "$pid1" -n -- ip link set veth-ct1 up
nsenter -t "$pid1" -n -- ip route add default via 172.20.0.1

nsenter -t "$pid2" -n -- ip link set lo up
nsenter -t "$pid2" -n -- ip addr add 172.20.0.3/24 dev veth-ct2
nsenter -t "$pid2" -n -- ip link set veth-ct2 up
nsenter -t "$pid2" -n -- ip route add default via 172.20.0.1

echo "Testing container-to-container ping across bridge..."
nsenter -t "$pid1" -n -- ping -c 2 -W 2 172.20.0.3
echo "PASS: ct1 -> ct2 ping"

nsenter -t "$pid2" -n -- ping -c 2 -W 2 172.20.0.2
echo "PASS: ct2 -> ct1 ping"

echo "Testing container-to-bridge gateway ping..."
nsenter -t "$pid1" -n -- ping -c 2 -W 2 172.20.0.1
echo "PASS: ct1 -> bridge gateway ping"

echo "Testing iptables NAT MASQUERADE rule setup..."
iptables -t nat -A POSTROUTING -s 172.20.0.0/24 ! -o br-test0 -j MASQUERADE
iptables -t nat -L POSTROUTING -n -v | grep 172.20.0.0
iptables -t nat -D POSTROUTING -s 172.20.0.0/24 ! -o br-test0 -j MASQUERADE
echo "PASS: iptables NAT rule verified"

echo "CONTAINER_NETWORKING_PASS"
