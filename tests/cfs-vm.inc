
mkdir -p /sys/fs/cgroup /run/legacy-blkio
controllers='+cpu +cpuset +memory +pids'
if grep -Eq '(^| )cgroup_no_v1=all(,named)?( |$)' /proc/cmdline; then
    if mount -t cgroup -o blkio blkio /run/legacy-blkio; then
        echo 'Legacy blkio mounted during unified-mode test' >&2
        exit 1
    fi
    controllers="$controllers +io"
else
    mount -t cgroup -o blkio blkio /run/legacy-blkio
fi
mount -t cgroup2 none /sys/fs/cgroup
if [ "$controllers" = '+cpu +cpuset +memory +pids' ] && grep -qw io /sys/fs/cgroup/cgroup.controllers; then
    echo 'Block I/O unexpectedly available on the unified hierarchy' >&2
    exit 1
fi
printf '%s\n' "$controllers" > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/apps /sys/fs/cgroup/runtime
printf '%s\n' "$controllers" > /sys/fs/cgroup/runtime/cgroup.subtree_control
if grep -qw io /sys/fs/cgroup/runtime/cgroup.subtree_control; then
    test -r /sys/fs/cgroup/runtime/io.stat
fi
limit=/sys/fs/cgroup/runtime/limited
for attempt in 1 2; do
    mkdir "$limit"
    printf '10000 100000\n' > "$limit/cpu.max"
    printf '67108864\n' > "$limit/memory.max"
    printf '32\n' > "$limit/pids.max"
    test -n "$(cat "$limit/cpuset.cpus.effective")"
    workers=
    for cpu in 0 1; do
        taskset -c "$cpu" /bin/sh -c 'printf "0\n" > "$1/cgroup.procs" && exec yes' sh "$limit" >/dev/null &
        workers="$workers $!"
    done
    sleep 2
    for worker in $workers; do
        kill "$worker"
        wait "$worker" || true
    done
    cat "$limit/cpu.stat"
    awk '$1 == "nr_throttled" && $2 > 0 {found=1} END {exit !found}' "$limit/cpu.stat"
    rmdir "$limit"
done
echo CFS_THROTTLE_PASS

# Keep app memory and freezer accounting on a process group while moving
# its threads between scheduling groups inside the same resource domain.
android=/sys/fs/cgroup/apps
printf '%s\n' "$controllers" > "$android/cgroup.subtree_control"
mkdir "$android/uid_10000" "$android/uid_10001"
for uid in "$android/uid_10000" "$android/uid_10001"; do
    printf '%s\n' "$controllers" > "$uid/cgroup.subtree_control"
done
app=$android/uid_10000/pid_123
other=$android/uid_10001/pid_124
mkdir "$app" "$other"
for domain in "$app" "$other"; do
    scheduler=$domain/vegas26-sched
    mkdir "$scheduler"
    printf 'threaded\n' > "$scheduler/cgroup.type"
    printf '%s\n' '+cpu +cpuset' > "$domain/cgroup.subtree_control"
    printf '%s\n' '+cpu +cpuset' > "$scheduler/cgroup.subtree_control"
    # The Android task action takes an advisory lock on this directory.
    flock "$scheduler" true
    mkdir "$scheduler/foreground" "$scheduler/background"
    mkdir "$scheduler/background/system-affinity"
    for group in "$scheduler/foreground" "$scheduler/background" "$scheduler/background/system-affinity"; do
        printf 'threaded\n' > "$group/cgroup.type"
    done
    printf '0\n' > "$scheduler/foreground/cpuset.cpus"
    printf '0-1\n' > "$scheduler/background/cpuset.cpus"
    printf '%s\n' '+cpuset' > "$scheduler/background/cgroup.subtree_control"
    printf '1\n' > "$scheduler/background/system-affinity/cpuset.cpus"
    printf '400\n' > "$scheduler/foreground/cpu.weight"
    printf '100\n' > "$scheduler/background/cpu.weight"
done
scheduler=$app/vegas26-sched
test "$(cat "$app/cgroup.type")" = 'domain threaded'
printf '67108864\n' > "$app/memory.max"
test ! -e "$scheduler/foreground/memory.max"
if grep -qw io "$android/cgroup.subtree_control"; then
    printf '10\n' > "$app/io.bfq.weight"
    printf 'restrict-to-be\n' > "$app/io.prio.class"
    grep -Eq '^(default )?10$' "$app/io.bfq.weight"
    grep -Fxq restrict-to-be "$app/io.prio.class"
    test ! -e "$scheduler/foreground/io.bfq.weight"
    echo VEGAS26_IO_POLICY_PASS
fi

sh -c 'printf "0\n" > "$1/cgroup.procs" && exec sleep 60' sh "$app" &
worker=$!
for attempt in 1 2 3 4 5; do
    grep -qx "$worker" "$app/cgroup.procs" && break
    sleep 0.1
done
grep -qx "$worker" "$app/cgroup.procs"
for group in "$scheduler/foreground" "$scheduler/background" "$scheduler/background/system-affinity"; do
    printf '%s\n' "$worker" > "$group/cgroup.threads"
    grep -qx "$worker" "$group/cgroup.threads"
    grep -qx "$worker" "$app/cgroup.procs"
    mask=$(cat "$group/cpuset.cpus.effective")
    awk -v mask="$mask" '$1 == "Cpus_allowed_list:" && $2 == mask { found=1 } END { exit !found }' "/proc/$worker/status"
done
# An affinity-only transition must keep the existing CPU policy.
test "$(cat "$scheduler/background/cpu.weight")" = 100
test ! -e "$scheduler/background/system-affinity/cpu.weight"
test "$(cat "$scheduler/background/cpuset.cpus.effective")" != "$(cat "$scheduler/background/system-affinity/cpuset.cpus.effective")"
if (printf '%s\n' "$worker" > "$other/vegas26-sched/foreground/cgroup.threads") 2>/dev/null; then
    echo 'Thread unexpectedly moved between app memory domains' >&2
    exit 1
fi
printf '1\n' > "$app/cgroup.freeze"
for attempt in 1 2 3 4 5; do
    grep -qx 'frozen 1' "$app/cgroup.events" && break
    sleep 0.1
done
grep -qx 'frozen 1' "$app/cgroup.events"
grep -qx 'frozen 0' /sys/fs/cgroup/runtime/cgroup.events
printf '0\n' > "$app/cgroup.freeze"
kill "$worker"
wait "$worker" || true
echo ANDROID_THREADED_CGROUPS_PASS

# WebView's renderer starts in the system-side zygote's cgroup. Android's
# system_server (UID 1000) places it in an isolated app resource domain.
mkdir /sys/fs/cgroup/system "$android/uid_99000"
printf '%s\n' "$controllers" > /sys/fs/cgroup/system/cgroup.subtree_control
printf '%s\n' "$controllers" > "$android/uid_99000/cgroup.subtree_control"
source=/sys/fs/cgroup/system/webview-zygote
mkdir "$source"
chown 1000:1000 /sys/fs/cgroup/cgroup.procs
for mode in scheduled fallback; do
    target=$android/uid_99000/$mode
    specialize=/run/webview-specialize
    mkdir "$target"
    printf '33554432\n' > "$target/memory.max"
    chown 1000:1000 "$target" "$target/cgroup.procs" "$target/cgroup.subtree_control"
    if [ "$mode" = fallback ]; then
        chmod 0444 "$target/cgroup.subtree_control"
    else
        mkfifo "$specialize"
    fi
    /bin/sh -c '
        printf "0\n" > "$1/cgroup.procs"
        if test -p "$2"; then read -r ready < "$2"; fi
        exec setpriv --reuid 99000 --regid 99000 --clear-groups sleep 60
    ' sh "$source" "$specialize" &
    renderer=$!
    if [ "$mode" = scheduled ]; then
        for attempt in 1 2 3 4 5; do
            grep -qx "$renderer" "$source/cgroup.procs" && break
            sleep 0.1
        done
        grep -qx "$renderer" "$source/cgroup.procs"
        # Before dropping the spawning process's credentials, the kernel
        # should refuse the less-privileged caller's cpuset migration.
        if setpriv --reuid 1000 --regid 1000 --clear-groups /bin/sh -ec '
            printf "%s\n" "$1" > "$2/cgroup.procs"
        ' sh "$renderer" "$target"; then
            echo 'Expected migration to fail before renderer specialization' >&2
            exit 1
        fi
        printf 'ready\n' > "$specialize"
        rm "$specialize"
    fi
    for attempt in 1 2 3 4 5; do
        if grep -qx "$renderer" "$source/cgroup.procs" &&
           awk '$1 == "Uid:" && $2 == 99000 { found=1 } END { exit !found }' "/proc/$renderer/status"; then
            break
        fi
        sleep 0.1
    done
    grep -qx "$renderer" "$source/cgroup.procs"
    awk '$1 == "Uid:" && $2 == 99000 { found=1 } END { exit !found }' "/proc/$renderer/status"
    setpriv --reuid 1000 --regid 1000 --clear-groups /bin/sh -eu -c '
        printf "%s\n" "$1" > "$2/cgroup.procs"
        mkdir "$2/vegas26-sched"
        printf "threaded\n" > "$2/vegas26-sched/cgroup.type"
        if [ "$3" = scheduled ]; then
            printf "+cpu +cpuset\n" > "$2/cgroup.subtree_control"
            printf "+cpu +cpuset\n" > "$2/vegas26-sched/cgroup.subtree_control"
            printf "%s\n" "$1" > "$2/vegas26-sched/cgroup.threads"
        else
            if (printf "+cpu +cpuset\n" > "$2/cgroup.subtree_control"); then
                echo "Expected the optional controller write to be denied" >&2
                exit 1
            fi
            rmdir "$2/vegas26-sched"
        fi
    ' sh "$renderer" "$target" "$mode"
    grep -qx "$renderer" "$target/cgroup.procs"
    grep -Fxq 33554432 "$target/memory.max"
    if grep -qw io "$android/uid_99000/cgroup.subtree_control"; then
        test -r "$target/io.stat"
    fi
    if [ "$mode" = scheduled ]; then
        grep -qx "$renderer" "$target/vegas26-sched/cgroup.threads"
    else
        test ! -e "$target/vegas26-sched"
    fi
    kill "$renderer"
    wait "$renderer" || true
done
echo ANDROID_WEBVIEW_CGROUP_PLACEMENT_PASS
