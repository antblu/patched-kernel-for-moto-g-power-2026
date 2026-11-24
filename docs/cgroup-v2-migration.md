# Cgroup v2 Migration Architecture for Moto G Power 2026 (vegas26)

## 1. Overview and Current State

On the Moto G Power 2026 running Android 16 firmware `W1WEOS36.48-22-3-3-4-2`:
* The unified hierarchy is mounted at `/sys/fs/cgroup` (`cgroup2`). The K3s kernel exposes `pids` there when the Debian launcher shares the unified mount. The older launcher could take `pids` off v2 by mounting it on v1 inside its private mount namespace.
* Android's vendor configuration overrides the system cgroup definitions, mounting legacy v1 controllers:
  * `/dev/cpuctl` (`cpu`)
  * `/dev/cpuset` (`cpuset`)
  * `/dev/memcg` (`memory`)
  * `/dev/blkio` (`blkio`)
* In the Linux kernel, a controller bound to a cgroup v1 hierarchy cannot be added to cgroup v2 subtree control (`/sys/fs/cgroup/cgroup.subtree_control`).
* Container runtimes (containerd 2.x, Docker 29.x, and K3s agent) require `cpu` and `memory` under cgroup v2. Live execution of `k3s agent` confirmed this dependency with `Error: failed to find cpu cgroup (v2)`.

The PIDs canary added a vendor descriptor with `NeedsActivation: true` and `MaxActivationDepth: 1`. Before the canary, the root subtree control was empty. After boot, Android and Debian both reported `pids` in `cgroup.subtree_control`, and Android exposed `apps/pids.max`. The canary set no process limit. These kernel interfaces survived Magisk's overlay cleanup and confirmed the early descriptor took effect with SELinux enforcing. [Android 16 cgroup setup](https://android.googlesource.com/platform/system/core/+/android16-release/libprocessgroup/setup/cgroup_map_write.cpp) · [Magisk 31.1 overlay cleanup](https://github.com/topjohnwu/Magisk/blob/v31.1/native/src/core/daemon.rs#L359-L381)

Keep the final controller and task-profile definitions available to Android services after boot. Android 16 also reads controller descriptors from userspace, so a pre-init-only overlay leaves later readers with firmware defaults after Magisk removes it. [Android 16 descriptor loader](https://android.googlesource.com/platform/system/core/+/android16-release/libprocessgroup/util/util.cpp)

---

## 2. Descriptor Reconciliation (`cgroups.json`)

The target is a single cgroup v2 hierarchy with `cpu`, `cpuset`, `memory`, `pids`, and `io`, and no cgroup v1 mounts. CPU accounting and freezing use the v2 interfaces. Android reads the system, API-level and vendor descriptors in order and merges entries by controller name. Define `cpu`, `cpuset`, and `memory` explicitly on v2 in the vendor policy. Remove the legacy `blkio` entry from both system and vendor definitions, and reconcile the legacy I/O profiles with v2 `io` policy. The descriptor and init changes need to ship together because Android init writes controller attributes before starting services. [Android 16 descriptor loader](https://android.googlesource.com/platform/system/core/+/android16-release/libprocessgroup/util/util.cpp)

---

## 3. Task Profile Reconciliation (`task_profiles.json`)

The running `system_server` belongs to `/foreground` in both v1 scheduling hierarchies, `/system` in v1 memory, and `/system/uid_1000/pid_<pid>` in cgroup v2. Android uses the per-process v2 groups for lifecycle and freezer operations. Combining the v1 paths with a single global `foreground` group would move a process out of its existing domain. A write to `cgroup.threads` also cannot move a thread across domains. [Linux cgroup v2 thread mode](https://docs.kernel.org/5.15/admin-guide/cgroup-v2.html#threads)

Keep memory and freezer accounting at the existing process group. Put scheduling groups inside that domain so threads can move locally. A profile that changes only CPU scheduling or only CPU affinity needs to preserve the other dimension. For example, `OtaProfiles` currently selects `background` in CPU and `system-background` in cpuset. This layout needs a process-relative task-placement implementation in Android's process-group library. Upstream Android's `JoinCgroup` task action rejects app-dependent paths. [Android 16 task-profile implementation](https://android.googlesource.com/platform/system/core/+/android16-qpr2-release/libprocessgroup/task_profiles.cpp)

The `--cfs` ARM64 VM test checks this topology on the K3s kernel. It moves a task between two threaded children, verifies each CPU mask and the parent's process membership, rejects a move into a different memory domain, and freezes the app domain while the sibling runtime hierarchy stays unfrozen. Android's task-profile library and SELinux policy still need hardware validation with the new layout.

The `--unified` variant also passed with `cgroup_no_v1=all`. The legacy block I/O mount was rejected, and all five controllers were delegated to the runtime subtree. This validates the kernel configuration in QEMU. Android still needs the coordinated userspace changes on the phone.

On the phone, Fastboot accepted a diagnostic `boot_a` image with `cgroup_no_v1=all` in the v4 boot header. Its payload matched the flashed image, but the option was absent from the running kernel command line. The phone continued to expose only `pids` on cgroup v2. A kernel-enforced v1 restriction would need to reach the effective command line, for example through the built-in command line, alongside the Android policy changes.

Restore the AOSP `FileV2` mappings for `MemLimit` (`memory.max`) and `MemSoftLimit` (`memory.low`) that the vendor file overrides. `memory.high` throttles allocation and would change the soft limit's reclaim behavior. `memory.pressure` exposes PSI and needs a compatible reader. The legacy pressure event registration interface requires separate handling. [Android 16 task profiles](https://android.googlesource.com/platform/system/core/+/android16-release/libprocessgroup/profiles/task_profiles.json) · [Linux cgroup v2 memory interfaces](https://docs.kernel.org/5.15/admin-guide/cgroup-v2.html#memory-interface-files)

---

## 4. Early Init (`init.rc`) Compatibility

The firmware's main init script configures per-group swappiness and vendor reclaim knobs, including `memory.avail_buffers`, `memory.swapd_mcgs_setup`, and the reclaim skip intervals. The running phone had an `mswapd` worker and active zram swap. Its `moto_swap.ko` imports `cgroup_add_legacy_cftypes`, and the swap controls appear on the v1 mount. Linux 5.15 v2 has no per-group `memory.swappiness` interface. Preserving the vendor reclaim policy requires a v2-compatible implementation. The running `lmkd` already uses `/proc/pressure/memory`, which is separate from the vendor swap policy. Factory and meta boot scripts mount memory separately and need their own coverage. [Linux cgroup v2 memory interfaces](https://docs.kernel.org/5.15/admin-guide/cgroup-v2.html#memory-interface-files)

The tested `init_boot_a` overlay disables `moto_swap`, keeps stock `zram` loaded, and selects Android's standard swap setup. After the stock recovery rehearsal, the standalone recovery kernel restored the saved overlay. ADB verified Magisk root, SELinux enforcing, PIDs still delegated on cgroup v2, and `moto_swap` absent. [Verified recovery](recovery.md)

The memory-only canary is installed. It replaces the vendor memory descriptor with the AOSP v2 definition, restores the v2 memory attribute mappings, and keeps `system_server` in its existing `/system/uid_1000/pid_*` cgroup. An early action retains both vendor policy files through Magisk cleanup and gives them their original SELinux file types. The first attempt retained files labeled `tmpfs`, causing reads by Android services to fail. The corrected image booted with SELinux enforcing, verified policy hashes, and `memory` and `pids` enabled in the unified root. No v1 memory mount remained.

`system_server` reported usage in `memory.current`. A disposable Debian cgroup killed its test allocation at a 16 MiB memory limit, and all 18 Debian regression checks passed. Android's standard zram swap stayed active. The canary still carries the firmware's legacy memory commands in the main init script. Full pressure and Android lifecycle testing and cleanup of those obsolete commands remain pending for a production image. CPU, cpuset, and block I/O still use v1.

Motorola product init changes several CPU masks after the base init rules. Preserve the effective masks and check the MediaTek power HAL's `cpu.uclamp.*` accesses against the new paths and SELinux labels. The pinned kernel registers `cpu.uclamp.latency_sensitive` in both hierarchies. Widevine, Dolby, media codec, and transcoding scripts contain legacy `writepid` entries. Android 16 already translates the `foreground` and `system-background` cpuset paths to task profiles, so those services depend on the migrated profile behavior. [Android 16 service parser](https://android.googlesource.com/platform/system/core/+/android16-release/init/service_parser.cpp)

---

## 5. Verification Checklist

1. **Early Boot & Compositor**: SurfaceFlinger renders launcher and reacts to touch with unified task placement.
2. **Audio & Media**: Verify audioserver and MediaTek power HAL adjust uclamp latency sensitivity on cgroup v2.
3. **Camera HAL**: Camera daemon process switches between `camera-daemon` and `background` without crashes.
4. **Container Runtime Subtree Delegation**:
   ```sh
   mkdir /sys/fs/cgroup/runtime
   printf '+cpu +cpuset +memory +pids\n' > /sys/fs/cgroup/cgroup.subtree_control
   printf '+cpu +cpuset +memory +pids\n' > /sys/fs/cgroup/runtime/cgroup.subtree_control
   ```
5. **K3s Agent Registration**: Node registers successfully against an external control plane using the delegated `/sys/fs/cgroup/runtime` subtree.
