
ip netns add brpeer1
ip netns add brpeer2
ip link add smoke-br type bridge
ip link add smoke1 type veth peer name test0 netns brpeer1
ip link add smoke2 type veth peer name test0 netns brpeer2
ip link set smoke1 master smoke-br
ip link set smoke2 master smoke-br
ip link set smoke-br up
ip link set smoke1 up
ip link set smoke2 up
ip -n brpeer1 addr add 198.51.100.9/30 dev test0
ip -n brpeer2 addr add 198.51.100.10/30 dev test0
ip -n brpeer1 link set test0 up
ip -n brpeer2 link set test0 up
printf '1\n' > /proc/sys/net/bridge/bridge-nf-call-iptables
ip netns exec brpeer1 ping -c 1 -W 3 198.51.100.10
iptables-legacy -A FORWARD -p icmp -j DROP
if ip netns exec brpeer1 ping -c 1 -W 2 198.51.100.10; then
    echo 'Bridge filter failed to block matching packets' >&2
    exit 1
fi
iptables-legacy -D FORWARD -p icmp -j DROP
ip netns exec brpeer1 ping -c 1 -W 3 198.51.100.10
echo BRIDGE_NETFILTER_PASS
