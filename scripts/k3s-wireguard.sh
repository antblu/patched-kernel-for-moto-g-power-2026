#!/bin/sh
set -eu

action=${1:?missing overlay action}
config=${2:?missing WireGuard configuration}
iface=wg-k3s
owner=vegas26-k3s-overlay
address=${3:?missing WireGuard IPv4 interface address and prefix}
mtu=${4:-1120}
network=$(python3 -c 'import ipaddress, sys; print(ipaddress.IPv4Interface(sys.argv[1]).network)' "$address")
case "$mtu" in ''|*[!0-9]*) exit 2 ;; esac
[ "$mtu" -ge 576 ] && [ "$mtu" -le 65535 ] || exit 2
priority=103
protocol=242

owned_link() {
    [ "$(cat "/sys/class/net/$iface/ifalias" 2>/dev/null)" = "$owner" ]
}

remove_rule() {
    ip -4 rule del priority "$priority" to "$network" lookup main protocol "$protocol" 2>/dev/null || :
}

case "$action" in
    down)
        if owned_link; then
            ip link del "$iface"
            remove_rule
        fi
        exit
        ;;
    up) ;;
    *) exit 2 ;;
esac

rules=$(ip -4 -N rule show priority "$priority")
expected=$(printf '%s' "$network" | sed 's/[.]/[.]/g')
expected="^${priority}:[[:space:]]+from all to $expected lookup 254 proto $protocol[[:space:]]*$"
if [ -n "$rules" ] && printf '%s\n' "$rules" | grep -Evq "$expected"; then
    printf 'K3s WireGuard routing priority %s is occupied\n' "$priority" >&2
    exit 1
fi
if ip link show dev "$iface" >/dev/null 2>&1; then
    owned_link
else
    ip link add dev "$iface" type wireguard
    if ! ip link set dev "$iface" alias "$owner"; then
        ip link del "$iface"
        exit 1
    fi
fi
cleanup() {
    ip link del "$iface"
    remove_rule
}
trap cleanup EXIT
wg syncconf "$iface" "$config"
ip address replace "$address" dev "$iface"
ip link set dev "$iface" mtu "$mtu" up
if [ -z "$rules" ]; then
    ip -4 rule add priority "$priority" to "$network" lookup main protocol "$protocol"
fi
trap - EXIT
