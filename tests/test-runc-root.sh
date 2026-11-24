#!/bin/sh
# Run inside the candidate Debian instance with the bundled runc and static BusyBox.
set -eu
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 ABSOLUTE_RUNC ABSOLUTE_STATIC_BUSYBOX" >&2
    exit 2
fi
runc=$1
busybox=$2
work=$(mktemp -d)
container=${work##*/}
runtime() { "$runc" --root "$work/state" "$@"; }
cleanup() {
    runtime delete --force "$container" 2>/dev/null || :
    rm -rf -- "$work"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
mkdir -p "$work/rootfs/bin" "$work/rootfs/proc"
cp "$busybox" "$work/rootfs/bin/busybox"
printf '%s\n' "$container" > "$work/rootfs/runc-root-marker"
chmod 755 "$work/rootfs" "$work/rootfs/bin" "$work/rootfs/bin/busybox"
chmod 644 "$work/rootfs/runc-root-marker"
cat > "$work/config.json" <<'EOF'
{
  "ociVersion": "1.0.2",
  "process": {
    "terminal": false,
    "user": {"uid": 65534, "gid": 65534},
    "args": ["/bin/busybox", "sleep", "60"],
    "cwd": "/",
    "noNewPrivileges": true
  },
  "root": {"path": "rootfs", "readonly": true},
  "linux": {
    "namespaces": [{"type": "mount"}, {"type": "pid"}]
  },
  "mounts": [
    {"destination": "/proc", "type": "proc", "source": "proc"},
    {"destination": "/dev", "type": "tmpfs", "source": "tmpfs", "options": ["mode=755"]}
  ]
}
EOF
runtime run --detach --bundle "$work" "$container"
result=$(runtime exec --user 65534:65534 "$container" /bin/busybox sh -ec '
    test "$(/bin/busybox id -u)" = 65534
    /bin/busybox cat /runc-root-marker
')
test "$result" = "$container"
echo RUNC_EXEC_ISOLATION_PASS
