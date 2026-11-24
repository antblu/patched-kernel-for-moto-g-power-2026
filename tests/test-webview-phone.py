"""Exercise isolated WebView renderer creation on the connected vegas26 phone."""

import argparse
import re
import shlex
import subprocess
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--require-unified", action="store_true")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    adb = [args.adb]
    if args.serial:
        adb.extend(["-s", args.serial])

    def run(*command, check=True, input=None):
        return subprocess.run(adb + list(command), input=input, capture_output=True,
                              text=True, check=check, timeout=25).stdout.strip()

    def shell(*command, check=True):
        return run("shell", shlex.join(command), check=check)

    def root(command):
        return shell("su", "-c", command)

    def renderers():
        return {
            int(line.split()[0])
            for line in root("ps -A -o PID,NAME").splitlines()
            if re.search(r"com\.google\.android\.webview.*:sandboxed_process", line)
        }

    if shell("getprop", "ro.product.device") != "vegas26":
        raise RuntimeError("Expected a vegas26 phone")
    if shell("getprop", "sys.boot_completed") != "1" or shell("getenforce") != "Enforcing":
        raise RuntimeError("Expected a completed Android boot with SELinux enforcing")
    if args.require_unified and "cgroup_no_v1=all,named" not in root("cat /proc/cmdline").split():
        raise RuntimeError("Expected cgroup_no_v1=all,named")
    system_server = shell("pidof", "system_server")
    if not system_server or shell("pidof", "com.android.htmlviewer", check=False):
        raise RuntimeError("Expected system_server to be running and HTMLViewer to be idle")

    name = f"vegas26-webview-{uuid.uuid4().hex}.html"
    path = "/sdcard/Download/" + name
    media = "content://media/external/file"
    uri = None
    try:
        run("exec-in", "cat > " + shlex.quote(path),
            input="<!doctype html><title>vegas26</title><p>Local renderer probe</p>\n")
        shell("am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
              "-d", "file://" + path)
        for _ in range(15):
            row = shell("content", "query", "--uri", media, "--projection", "_id",
                        "--where", f"_display_name='{name}'")
            match = re.search(r"_id=(\d+)", row)
            if match:
                uri = f"{media}/{match[1]}"
                break
            time.sleep(1)
        if uri is None:
            raise RuntimeError("MediaStore did not index the probe document")

        for iteration in range(1, args.iterations + 1):
            before = renderers()
            launch = shell("am", "start", "-W", "-a", "android.intent.action.VIEW",
                           "-d", uri, "-t", "text/html", "--grant-read-uri-permission",
                           "-p", "com.android.htmlviewer")
            if "Status: ok" not in launch:
                raise RuntimeError(f"HTMLViewer launch {iteration} failed")
            fresh = set()
            for _ in range(20):
                fresh = renderers() - before
                if fresh:
                    break
                time.sleep(0.25)
            if not fresh:
                raise RuntimeError(f"No new renderer on launch {iteration}")
            domains = [
                root(f"cat /proc/{pid}/cgroup 2>/dev/null || true").splitlines()
                for pid in sorted(fresh)
            ]
            for membership in domains:
                domain = next((re.match(r"^0::(/apps/uid_\d+/pid_\d+)(?:/|$)", entry)
                               for entry in membership if entry.startswith("0::")), None)
                if domain and (not args.require_unified or len(membership) == 1):
                    break
            else:
                raise RuntimeError(f"Renderer was outside its app cgroup on launch {iteration}")
            if args.require_unified:
                group = shlex.quote(f"/sys/fs/cgroup{domain[1]}")
                root(f'test -r {group}/memory.max && test -r {group}/io.stat && '
                     f'test "$(cat {group}/vegas26-sched/cgroup.type)" = threaded')
            shell("am", "force-stop", "com.android.htmlviewer")
            if shell("pidof", "system_server") != system_server:
                raise RuntimeError(f"system_server restarted during launch {iteration}")
            print(f"PASS WebView launch {iteration}", flush=True)
    finally:
        shell("am", "force-stop", "com.android.htmlviewer", check=False)
        if uri:
            shell("content", "delete", "--uri", uri, check=False)
        shell("rm", "-f", path, check=False)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
