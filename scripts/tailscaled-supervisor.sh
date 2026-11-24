#!/bin/sh
set -eu

mkdir -p /var/lib/tailscale /run/tailscale /var/log

# Ensure /dev/net/tun exists
mkdir -p /dev/net
if [ ! -e /dev/net/tun ]; then
    mknod /dev/net/tun c 10 200 2>/dev/null || true
    chmod 666 /dev/net/tun 2>/dev/null || true
fi

# Ensure policy routing rules in shared netns
ip rule add priority 5220 fwmark 0x80000/0xff0000 lookup wlan0 2>/dev/null || true
ip rule add priority 97 to 100.64.0.0/10 lookup 52 2>/dev/null || true

# Supervise tailscaled
while true; do
    printf '%s Starting tailscaled...\n' "$(date -u +%FT%TZ)"
    /usr/local/bin/tailscaled \
        --state=/var/lib/tailscale/tailscaled.state \
        --socket=/run/tailscale/tailscaled.sock \
        --port=41641 > /var/log/tailscaled.log 2>&1 || status=$?
    printf '%s tailscaled exited (%s), restarting in 5s...\n' "$(date -u +%FT%TZ)" "${status:-0}"
    sleep 5
done
