#!/system/bin/sh
set -eu

echo "=== 1. Checking k3s binary ==="
/system/bin/sh /data/adb/debian-shell --enter /usr/local/bin/k3s --version

echo "=== 2. Running k3s configuration check ==="
config_out=$(/system/bin/sh /data/adb/debian-shell --enter /usr/local/bin/k3s check-config 2>&1 || true)
echo "$config_out" | grep "cgroup hierarchy"
echo "$config_out" | grep "CONFIG_CFS_BANDWIDTH"

echo "=== 3. Executing live k3s agent probe ==="
agent_log=$(/system/bin/sh /data/adb/debian-shell --enter timeout 12 /usr/local/bin/k3s agent \
    --data-dir /tmp/k3s-agent-probe \
    --server https://127.0.0.1:6443 \
    --token probe-token \
    --node-ip 127.0.0.1 \
    --prefer-bundled-bin \
    --snapshotter native \
    2>&1 || true)

echo "$agent_log"

# Assert key milestones
echo "$agent_log" | grep -q "Starting k3s agent" || { echo "FAIL: k3s agent failed to start" >&2; exit 1; }
echo "$agent_log" | grep -q "Running load balancer k3s-agent-load-balancer" || { echo "FAIL: load balancer failed to initialize" >&2; exit 1; }
if echo "$agent_log" | grep -qi "failed to find cpu cgroup"; then
    echo "FAIL: cgroup error detected" >&2
    exit 1
fi

/system/bin/sh /data/adb/debian-shell --enter rm -rf /tmp/k3s-agent-probe
echo "K3S_AGENT_READY_PASS"
