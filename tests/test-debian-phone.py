"""Check the running Debian startup instance on an ADB-connected phone."""

import argparse
import shlex
import subprocess
import sys

TESTS = {
    "Debian 13 ARM64": '. /etc/os-release; test "$VERSION_ID" = 13 && test "$(dpkg --print-architecture)" = arm64',
    "tini is PID 1": 'test "$(cat /proc/1/comm)" = tini && test "$$" -gt 1',
    "bash": "bash -c 'test 2 -eq $((1+1))'",
    "process exit status": '/bin/sh -c "exit 37"; test "$?" -eq 37',
    "signals": 'sleep 30 & p=$!; kill -TERM "$p"; wait "$p"; test "$?" -gt 128',
    "temporary files and links": (
        'd=$(mktemp -d); trap \'rm -f "$d/test" "$d/link"; rmdir "$d"\' EXIT; '
        'printf test > "$d/test" && chmod 600 "$d/test" && ln "$d/test" "$d/link" && '
        'test "$(cat "$d/link")" = test && test "$(stat -c %a "$d/test")" = 600'
    ),
    "device nodes": "test -c /dev/null && head -c 1 /dev/urandom >/dev/null",
    "private PTY": "script -qec 'test -t 0 && test -t 1' /dev/null",
    "shared memory directory": 'test "$(stat -c %a /dev/shm)" = 1777 && test -w /dev/shm',
    "unified cgroup mount": (
        'test "$(stat -f -c %T /sys/fs/cgroup)" = cgroup2fs && '
        'test -r /sys/fs/cgroup/cgroup.controllers'
    ),
    "DNS": "getent ahostsv4 deb.debian.org >/dev/null",
    "APT package indexes": "apt-get -o APT::Update::Error-Mode=any update >/dev/null",
    "APT-installed init package": "dpkg-query -W tini >/dev/null",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    adb = parser.parse_args().adb
    failures = 0
    for namespace in ("pid", "mnt", "ipc", "uts", "net"):
        probe = f"readlink /proc/self/ns/{namespace}"
        outer = subprocess.run([adb, "shell", probe], capture_output=True, timeout=20)
        inner = subprocess.run(
            [adb, "shell", "su -c " + shlex.quote("/system/bin/sh /data/adb/debian-shell --enter " + probe)],
            capture_output=True, timeout=20,
        )
        shared = namespace == "net"
        passed = (outer.returncode == inner.returncode == 0 and bool(outer.stdout.strip())
                  and ((outer.stdout.strip() == inner.stdout.strip()) == shared))
        print(f"{'PASS' if passed else 'FAIL'} {'shared' if shared else 'isolated'} {namespace} namespace", flush=True)
        failures += not passed
    for label, test in TESTS.items():
        command = "/system/bin/sh /data/adb/debian-shell --enter /bin/sh -c " + shlex.quote(test)
        try:
            result = subprocess.run(
                [adb, "shell", "su -c " + shlex.quote(command)], capture_output=True, timeout=180,
            )
            passed = result.returncode == 0
        except subprocess.TimeoutExpired:
            passed = False
        print(f"{'PASS' if passed else 'FAIL'} {label}", flush=True)
        failures += not passed
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
