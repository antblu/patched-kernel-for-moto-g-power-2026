# Run Debian 13 ARM64 at Android startup

Use a phone running the [namespace kernel](building.md), working Magisk root and BusyBox, USB debugging, Python 3.11 or newer, Docker, and ADB. Debian stays under `/data/adb/debian-trixie`.

## Install

From the repository root:

```sh
python3 scripts/install-debian.py
adb reboot
```

Use `--adb <path-to-adb>` if ADB is outside PATH. On WSL, a working Windows Platform-Tools executable is also usable via its mounted path. Add `--reuse` to preserve an existing trixie filesystem while updating its launcher, resolver, and startup hook.

The installer downloads and exports the digest-pinned official ARM64 Debian image, verifies the archive after transferring it, installs Debian's `tini` package, and registers a Magisk startup service. After Android finishes booting, the service launches `tini` as PID 1 inside Debian's PID namespace. Android retains its own init. The Debian instance has separate PID, mount, IPC, and UTS namespaces and shares Android's network. DNS is copied from Android's active network during setup. Run the installer with `--reuse` to refresh it after a network change.

## Enter and test

```sh
adb shell -t "su -c '/system/bin/sh /data/adb/debian-shell --enter'"
python3 tests/test-debian-phone.py
```

The shell joins the Debian instance started during boot. To disable automatic startup, move `/data/adb/service.d/90-debian-trixie.sh` outside Magisk's service directory as root, then reboot Android.

## Test results

On the test phone, a fresh Android reboot started Debian automatically. The test suite verified Debian 13 ARM64, `tini` as PID 1, the namespace boundaries, Bash, child exit status, signals, file permissions and hard links, device nodes, private pseudoterminals, the writable shared memory directory, DNS, APT index updates, and the installed init package.

This is a usable Debian command-line environment. Debian uses the Android kernel, shares the phone's network, and uses `tini` for startup. Full systemd service management and direct hardware access from Debian remain outside the verified setup.

## OCI and K3s compatibility

### PID-controller build on the phone

Docker 29.10.0 started on a private Unix socket with VFS storage in an isolated network namespace and ran an ARM64 Debian container. With explicit PID controller delegation and a disposable cgroup parent, a container launched with `--pids-limit 1` reported `pids.max=1`. Docker rejected `--cpus 0.5` and discarded `--memory 64m` with a warning. The default NAT setup failed because Debian did not have `iptables`. A container attached to a bridge with firewall rules, forwarding, and masquerading disabled. The bridge probe did not establish packet connectivity. Temporary runtimes and cgroups were cleaned up, and the original cgroup delegation was restored.

On the flashed PID-controller build, `pids` is the only controller exposed on cgroup v2. Android holds the CPU, cpuset, memory, and I/O controllers on v1. The running kernel has `CONFIG_VXLAN` and `CONFIG_CFS_BANDWIDTH` disabled. Creating a VXLAN link in a disposable network namespace returned an unsupported-operation error. K3s startup, node registration, and pod networking were not demonstrated.

### Native K3s prerequisites on vegas26

After flashing the combined PID and VXLAN image, K3s v1.37.2+k3s1 `check-config` detected VXLAN and the mounted cgroup v2 hierarchy. It still rejected the available controller set because CPU, cpuset, and memory were missing from v2. It also flagged bridge netfilter, the iptables `addrtype` match, and legacy device and IPVS options. Validate the device policy through cgroup v2 BPF and choose the kube-proxy backend before treating the legacy device and IPVS flags as requirements.

The isolated CFS bandwidth experiment changed 64 export CRCs in two scheduler objects. Comparing those changes with the firmware's stock modules found 97 mismatched imports across 36 `vendor_dlkm` modules and 38 across 23 early-boot modules. The single-option build is unsuitable for the stock module sets. The changed types include `struct cfs_bandwidth` and `struct cfs_rq`. Moving quota state out of those layouts preserved the tested scheduler object CRCs. The patched production-configuration build preserved every shared export CRC and passed the versioned-import audit for all 399 stock modules. In QEMU it enforced `cpu.max` on two CPUs in successive cgroups with block I/O on v1 and CPU, cpuset, memory, and PIDs delegated on v2.

The CFS bandwidth profile was flashed to slot A on the test phone. Android completed boot, SELinux stayed enforcing, all 360 vendor modules loaded with 0 loader warnings, and `k3s check-config` verified `CONFIG_CFS_BANDWIDTH: enabled`. Hardware validation via `tests/test-cfs-phone.sh` enforced a 10% CPU quota (10,000 us per 100,000 us period) on two busy workers pinned to CPU 0 and CPU 1 via toybox `taskset`. The run observed 20/20 throttled periods and accumulated 3.69 seconds of enforced throttling (`CFS_HARDWARE_THROTTLE_PASS`).

Container bridge networking was also completed on hardware in `tests/test-container-bridge.sh`. Android Netd drops unclassified bridge routing by omitting table `main` (`32000: from all unreachable`). Inserting `ip rule add from all lookup main pref 9999` and whitelisting the bridge on `INPUT` and `FORWARD` established bidirectional container-to-container packet flow across bridge `br-test0` (0.14 - 0.21 ms latency, 0% packet loss), gateway ping, and iptables NAT MASQUERADE (`CONTAINER_NETWORKING_PASS`). Native `k3s agent` in Debian initialized datastore locks and confirmed cgroup v2 recognition, with `failed to find cpu cgroup (v2)` isolating the remaining dependency to cgroup v2 controller delegation.

Enabling bridge netfilter alone changed 172 export CRCs in `net/core/dev.o`. That one object accounted for 63 mismatched vendor_dlkm imports and 24 early-boot imports. The added bridge extension changes the `struct skb_ext` offset array. The layout-preserving prototype retains the original extension IDs and member offsets while using a padding byte for the extra extension. Its full build passed the versioned-import audit for all 399 stock modules. Nine shared export CRCs changed, and no stock module imported those symbols. In QEMU, an iptables forwarding rule blocked bridged ICMP traffic, and the traffic recovered after the rule was removed. The bridge profile has only been tested offline.

The firmware has legacy cgroup references in seven Android init files. The vendor cgroup descriptors override the system memory controller, and the task profiles depend on legacy paths. The pinned scheduler registers `cpu.uclamp.latency_sensitive` in both hierarchies using the same handlers. The vendor init references `prefer_cpu`, but that file was absent for `top-app` on the running device. Preserve CPU placement and effective masks and verify the power HAL's actual file access. Android still exposes the v1 `memory.swappiness` knob, so the unified memory policy needs explicit swap and pressure behavior. Validate Widevine and Dolby startup and the MediaTek power HAL along with boot, app launch, and suspend before delegating CPU, cpuset, memory, and PIDs to the container runtime. The live Android mounts and task profiles were used for inspection only.

Reading the system and vendor task-profile files found 12 aggregate profiles that select different paths in different legacy hierarchies. A unified hierarchy needs a single effective process placement, with threaded groups where per-thread policies require them. Leave block I/O on v1 for the first prototype because kubelet's cgroup v2 manager does not require `io`. The OTA profile still needs reconciliation because it uses `cpu/background` and `cpuset/system-background`. Review the vendor memory attributes as a separate group. The effective definitions have no v2 mappings for limit, usage, swap, and pressure controls. Verify these changes with an early-init test image before changing the active Android install.

### Earlier namespace build

An isolated Docker 29.10.0 test started after mounting cgroup v2 at `/sys/fs/cgroup`. It ran one local ARM64 Debian container with networking and resource limits disabled. The probe used a private Unix socket and a disposable cgroup. It used VFS storage and mounted the Debian root as its own mount point for OCI mount propagation. These settings were confined to the probe.

The unified hierarchy exposed no controllers. Docker rejected the CPU quota test, and a disposable child could not delegate CPU, memory, or PIDs on v2. Android's vendor profiles still use v1 for CPU, cpuset, memory, and block I/O. Keep Android's task profiles in place until an alternative has passed Android regression tests. The phone has not joined a K3s cluster.

In an ARM64 VM, the same kernel exposed CPU, memory, cpuset, and I/O controllers when booted without legacy cgroup controllers. A child cgroup supported `memory.max` and `cpu.weight`. The `cpu.max` and `pids.max` interfaces were absent. Moving Android's profiles to v2 would therefore address controller ownership, while hard CPU quotas and PID limits need separate kernel work.

The optional VXLAN build created a VXLAN link in QEMU and passed checks against all 399 vendor module files with no changed existing export CRCs. It remains an offline candidate.

Standalone containerd 2.4.2 responded on a private Unix socket on the phone. A local ARM64 workload using an unpacked Debian root filesystem stopped in runc because its disposable cgroup lacked `cpu.weight`. The test used a private network namespace and did not contact a cluster.

The phone's Android 16 vendor configuration overrides the system memory controller definition with a v1 mount and removes the v2 file mappings from the vendor memory-limit attributes. Android's init scripts also use legacy memory swappiness, MediaTek CPU latency-sensitive controls, cpuset paths, and block I/O settings directly. A v2 migration needs coordinated changes to those early-init actions and vendor profiles, with regression tests for each affected Android service. Replacing only the controller descriptors would leave those dependencies unresolved.

### Separate Linux guest

A temporary QEMU 10.0.13 ARM64 guest booted on the phone using software emulation and Debian's `6.12.117+deb13-arm64` kernel. With 2 virtual CPUs and 768 MiB RAM, the guest booted, ran the cgroup probe, and powered down in about nine seconds. Inside the guest, a child cgroup accepted writes to `cpu.max`, `memory.max`, and `pids.max`. The test did not load a sustained workload. The phone's kernel includes KVM, but the running Android system had no usable `/dev/kvm`.

The guest probe ran without networking. A separate Android test created and removed a TAP interface within a disposable network namespace. A routable guest interface, K3s registration, cross-node pod traffic, and sustained performance remain unverified. The temporary guest data was removed after the test.

A later guest on the combined kernel reached its QEMU user-mode gateway and resolved a public DNS name. That test exercised guest egress through QEMU's NAT. It did not establish a routable node address or inbound VXLAN.

A disposable K3s v1.37.2+k3s1 single-node trial used four software-emulated CPUs and 2304 MiB RAM. Its embedded containerd opened the CRI socket, but the API readiness probe never succeeded within the nine-minute window. The logs recorded localhost TLS handshake timeouts and Kine datastore deadlines. Node readiness and pod startup were unverified. The next guest trial should run an agent against a separate control plane using a routable test interface.
