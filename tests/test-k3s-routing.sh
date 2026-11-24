#!/usr/bin/env bash
# Run with root or CAP_SYS_ADMIN on a Linux host with iproute2 and Python 3.
set -euo pipefail
script=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../scripts" && pwd)/k3s-network.py
unshare --net bash -s -- "$script" <<'EOF'
set -euo pipefail
script=$1
pod=10.42.0.0/16
service=10.43.0.0/16
node=10.42.5.0/24
configure() { python3 "$script" "$1" "$pod" "$service" "$node"; }

ip link add wlan0 type dummy
ip link add cni0 type dummy
ip link set wlan0 up
ip -4 route add default dev wlan0 table 1036
configure apply
configure apply
[[ $(ip -4 rule show | grep -cE '^10[012]:') == 3 ]]
ip -4 -N rule show priority 102 | grep -Eq 'from 10\.42\.5\.0/24 iif cni0 lookup 1036'

ip -4 route del default dev wlan0 table 1036
configure apply
[[ -z $(ip -4 rule show priority 102) ]]
ip -4 route add default dev wlan0 table 1037
configure apply
ip -4 -N rule show priority 102 | grep -Eq 'from 10\.42\.5\.0/24 iif cni0 lookup 1037'

configure remove
if ip -4 rule show | grep -qE '^10[012]:'; then exit 1; fi
ip -4 rule add priority 100 to "$pod" lookup main
if configure apply; then exit 1; fi
configure remove
ip -4 rule show priority 100 | grep -Eq 'to 10\.42\.0\.0/16 lookup main'
echo K3S_SCOPED_ROUTING_PASS
EOF
