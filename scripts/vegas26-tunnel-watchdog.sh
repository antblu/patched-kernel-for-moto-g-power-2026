#!/usr/bin/env bash
set -euo pipefail

adb="/mnt/c/Users/antbl/MotoRoot/platform-tools/adb.exe"
if [[ ! -x "$adb" ]]; then
    adb="adb"
fi

phones=(
    "100.64.0.2:5555"
    "100.64.0.13:5555"
    "100.64.0.7:5555"
)
primary="100.64.0.2:5555"

run_once() {
    local devices
    devices=$("$adb" devices </dev/null 2>/dev/null || true)
    for p in "${phones[@]}"; do
        if ! grep -q "$p.*device" <<< "$devices"; then
            "$adb" connect "$p" </dev/null >/dev/null 2>&1 || true
        fi
    done

    local reverses
    reverses=$("$adb" -s "$primary" reverse --list </dev/null 2>/dev/null || true)
    if ! grep -q "16443" <<< "$reverses"; then
        "$adb" -s "$primary" reverse tcp:16443 tcp:16443 </dev/null >/dev/null 2>&1 || true
    fi
}

if [[ "${1:-}" == "--once" ]]; then
    run_once
    exit 0
fi

while true; do
    run_once
    sleep 10
done
