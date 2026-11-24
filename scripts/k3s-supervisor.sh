#!/bin/sh
set -eu

config=${1:?K3s agent config required}
scripts=$(dirname -- "$0")
[ ! -e "${config%/*}/disabled" ] || exit 0
umask 077
exec 8>>/run/vegas26-k3s-supervisor.lock
flock -n 8

# Android netd programs are already referenced by the legacy filter table.
test "$(stat -f -c %T /sys/fs/bpf)" = bpf_fs
sh "$scripts/check-k3s-cgroup-v2.sh" --host-only
iptables-legacy-save -t filter >/dev/null
test "$(cat /proc/1/comm)" = tini

agent=
network=
waker=
storage=
rancher_mount=
kubelet_mount=
saved_panic=
overlay=
stop() {
    if [ -n "$agent" ]; then
        kill -TERM "$agent" 2>/dev/null || :
        wait "$agent" || :
    fi
    if [ -n "$saved_panic" ] && [ "$(cat /proc/sys/kernel/panic)" = 10 ]; then
        printf '%s\n' "$saved_panic" > /proc/sys/kernel/panic || :
    fi
    if [ -n "$network" ]; then
        kill -TERM "$network" 2>/dev/null || :
        wait "$network" || :
    fi
    if [ -n "$overlay" ]; then
        sh "$scripts/k3s-wireguard.sh" down "$overlay" "$wireguard_address" "$wireguard_mtu" || :
    fi
    if [ -n "$waker" ]; then
        kill -TERM "$waker" 2>/dev/null || :
        wait "$waker" || :
        printf 'k3s_node\n' > /sys/power/wake_unlock || :
    fi
    if [ -n "$storage" ]; then
        if [ -n "$kubelet_mount" ]; then umount /var/lib/kubelet || :; fi
        if [ -n "$rancher_mount" ]; then umount /var/lib/rancher || :; fi
        python3 "$scripts/k3s-storage.py" unmount || :
    fi
}
trap stop EXIT
trap 'exit 0' HUP INT TERM

if [ -f "${config%/*}/ext4-storage" ]; then
    python3 "$scripts/k3s-storage.py" mount
    storage=ext4
    base=/var/lib/vegas26-k3s-storage
    for path in /var/lib/rancher /var/lib/kubelet; do
        if ! mountpoint -q "$path"; then
            if [ "$path" = /var/lib/rancher ]; then
                mkdir -p "$base/rancher" /var/lib/rancher
                mount --bind "$base/rancher" /var/lib/rancher
            else
                kubelet_data=$base/kubelet
                legacy_data=$base/lxc/k3s/rootfs/var/lib/kubelet
                if [ ! -d "$kubelet_data" ] && [ -d "$legacy_data" ]; then
                    kubelet_data=$legacy_data
                fi
                mkdir -p "$kubelet_data" /var/lib/kubelet
                mount --bind "$kubelet_data" /var/lib/kubelet
            fi
        fi
    done
    rancher_mount=ext4
    kubelet_mount=ext4
fi

if [ -f "${config%/*}/keep-awake" ]; then
    # Each acquisition expires if the supervisor or renewal process dies.
    printf 'k3s_node 60000000000\n' > /sys/power/wake_lock
    (
        while sleep 30; do
            printf 'k3s_node 60000000000\n' > /sys/power/wake_lock || exit
        done
    ) 8>&- &
    waker=$!
fi

overlay_config=${config%/*}/wireguard.conf
if [ -f "$overlay_config" ]; then
    read -r wireguard_address wireguard_mtu < "${config%/*}/wireguard-network.conf"
    sh "$scripts/k3s-wireguard.sh" up "$overlay_config" "$wireguard_address" "$wireguard_mtu"
    overlay=$overlay_config
elif [ -e /sys/class/net/tailscale0 ]; then
    test "$(cat /sys/class/net/tailscale0/operstate 2>/dev/null || :)" != "down"
    ts_ip=$(ip -4 -o addr show dev tailscale0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n 1)
    if [ -n "$ts_ip" ]; then
        ip addr replace "$ts_ip/10" dev tailscale0 2>/dev/null || true
    fi
fi

network_config=${config%/*}/network.conf
if [ -f "$network_config" ]; then
    IFS=' ' read -r pod_cidr service_cidr node_cidr < "$network_config"
    set -- "$pod_cidr" "$service_cidr" "$node_cidr"
    if [ -f "${config%/*}/wifi-interface" ]; then
        read -r wifi < "${config%/*}/wifi-interface"
        set -- "$@" --wifi "$wifi"
    fi
    if [ -f "${config%/*}/transport.conf" ]; then
        IFS=' ' read -r advertised relay api_service < "${config%/*}/transport.conf"
        set -- "$@" --relay "$advertised" "$relay"
        if [ -n "$api_service" ]; then set -- "$@" --service-api "$api_service"; fi
    fi
    python3 "$scripts/k3s-network.py" apply "$@"
    if [ -f "${config%/*}/allow-uid-65532" ]; then
        set -- "$@" --allow-uid-65532
    fi
    python3 "$scripts/k3s-network.py" watch "$@" 8>&- &
    network=$!
fi

# The shell owns the supervisor lock. The runtime launcher locks the agent.
saved_panic=$(cat /proc/sys/kernel/panic)
mode=server
if [ -f "${config%/*}/mode" ]; then
    read -r mode < "${config%/*}/mode"
fi
until [ -e "${config%/*}/disabled" ]; do
    if [ -n "$network" ] && ! kill -0 "$network" 2>/dev/null; then
        python3 "$scripts/k3s-network.py" watch "$@" 8>&- &
        network=$!
    fi
    sh "$scripts/run-in-k3s-runtime.sh" \
        /usr/local/bin/k3s "$mode" --config "$config" 8>&- &
    agent=$!
    if wait "$agent"; then status=0; else status=$?; fi
    agent=
    printf '%s K3s %s exited (%s)\n' "$(date -u +%FT%TZ)" "$mode" "$status"
    sleep 15
done
