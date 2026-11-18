# Cgroup v2 Migration Architecture for Moto G Power 2026 (vegas26)

## 1. Overview and Current State

On the Moto G Power 2026 running Android 16 firmware `W1WEOS36.48-22-3-3-4-2`:
* The unified hierarchy is mounted at `/sys/fs/cgroup` (`cgroup2`), but only exposes `pids` and `freezer`.
* Android's vendor configuration overrides the system cgroup definitions, mounting legacy v1 controllers:
  * `/dev/cpuctl` (`cpu`)
  * `/dev/cpuset` (`cpuset`)
  * `/dev/memcg` (`memory`)
  * `/dev/blkio` (`blkio`)
* In the Linux kernel, a controller bound to a cgroup v1 hierarchy cannot be added to cgroup v2 subtree control (`/sys/fs/cgroup/cgroup.subtree_control`).
* Container runtimes (containerd 2.x, Docker 29.x, and K3s agent) require `cpu` and `memory` under cgroup v2. Live execution of `k3s agent` confirmed this dependency with `Error: failed to find cpu cgroup (v2)`.

---

## 2. Descriptor Reconciliation (`cgroups.json`)

### Legacy Hierarchy (`Cgroups`)
Leave `blkio` on v1 for the initial prototype (`/dev/blkio`), because kubelet's cgroup v2 manager does not mandate `io`. Remove `cpu`, `cpuset`, and `memory` from v1:

```json
{
  "Cgroups": [
    {
      "Controller": "blkio",
      "Path": "/dev/blkio",
      "Mode": "0775",
      "UID": "system",
      "GID": "system"
    }
  ],
  "Cgroups2": {
    "Path": "/sys/fs/cgroup",
    "Mode": "0775",
    "UID": "system",
    "GID": "system",
    "Controllers": [
      {
        "Controller": "freezer",
        "Path": "."
      },
      {
        "Controller": "cpu",
        "Path": "."
      },
      {
        "Controller": "cpuset",
        "Path": "."
      },
      {
        "Controller": "memory",
        "Path": ".",
        "NeedsActivation": true,
        "MaxActivationDepth": 3,
        "Optional": true
      }
    ]
  }
}
```

---

## 3. Task Profile Reconciliation (`task_profiles.json`)

Inspection of `/system/etc/task_profiles.json` and `/vendor/etc/task_profiles.json` identified 47 action profiles and 19 aggregate profiles.

### Aggregate Profiles Replaced
12 aggregate profiles currently assign processes and threads to divergent paths across separate v1 hierarchies:
* `CPUSET_SP_TOP_APP` / `SCHED_SP_TOP_APP`: Unify to single v2 subtree `top-app`.
* `CPUSET_SP_FOREGROUND` / `SCHED_SP_FOREGROUND`: Unify to `foreground`.
* `CPUSET_SP_FOREGROUND_WINDOW` / `SCHED_SP_FOREGROUND_WINDOW`: Unify to `foreground_window`.
* `SCHED_SP_SYSTEM`: Unify to `system-background`.
* `SCHED_SP_RT_APP`: Map to `rt` with `cpu.uclamp.latency_sensitive=1`.
* `Dex2OatBackground` / `Dex2OatBootComplete`: Map to `dex2oat`.
* `OtaProfiles`: Reconcile `cpuset/system-background` and `cpu/background` into a single process group.

### Attribute Mappings
* **CPU Weights**: Map legacy `cpu.shares` ($2 \dots 262144$) to v2 `cpu.weight` ($1 \dots 10000$):
  * `top-app`: 5120 $\to$ 500
  * `foreground`: 4096 $\to$ 400
  * `background`: 1024 $\to$ 100
* **Memory Limits**:
  * `MemLimit` (`memory.limit_in_bytes`) $\to$ `memory.max`
  * `MemSoftLimit` (`memory.soft_limit_in_bytes`) $\to$ `memory.high`
  * `MemUsage` (`memory.usage_in_bytes`) $\to$ `memory.current`
  * `MemStats` (`memory.stat`) $\to$ `memory.stat`
  * `MemPressureLevel` $\to$ Pressure Stall Information (`memory.pressure`)

---

## 4. Early Init (`init.rc`) Compatibility

`/system/etc/init/hw/init.rc` contains early-init writes before services start:
* Direct swappiness writes:
  ```rc
  write /dev/memcg/apps/memory.swappiness 100
  write /dev/memcg/system/memory.swappiness 100
  ```
  *Resolution*: In unified cgroup v2, global swappiness is controlled via `vm.swappiness`. Create compatibility directory stubs or symlinks if init parser treats missing paths as fatal.
* Direct latency-sensitive uclamp writes:
  ```rc
  write /dev/cpuctl/nnapi-hal/cpu.uclamp.min 1
  write /dev/cpuctl/nnapi-hal/cpu.uclamp.latency_sensitive 1
  ```
  *Resolution*: The pinned kernel registers `cpu.uclamp.latency_sensitive` in both hierarchies using the same handler. Map these actions to `/sys/fs/cgroup/nnapi-hal/`.

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
