# Build the namespace kernel

Keep the source cache and build output on the Linux filesystem.

Builds and boot images are specific to the target device and firmware. The commands below describe this project’s tested Moto G Power 2026 setup; they are not a universal image recipe. For another phone or firmware, use the corresponding kernel source, configuration, vendor modules, and boot-image inputs. Build your own image, audit its module compatibility, and verify it on that exact hardware and firmware before use. The results documented here do not establish compatibility elsewhere.

```bash
bash scripts/setup-build-env.sh
bash scripts/fetch-sources.sh
JOBS=8 bash scripts/build-stock.sh
JOBS=8 bash scripts/build-stock.sh --namespaces
```

The fetcher checks the pinned Android Common Kernel and Clang archives before extraction. The first build produces the unmodified GKI reference. The second enables PID, user, and IPC namespaces, using POSIX message queues for the IPC dependency. Network, UTS, and time namespaces are built into the baseline. Both builds record artifact checksums in build-manifest.txt.

The cache defaults to `${XDG_CACHE_HOME:-$HOME/.cache}/moto-g-power-2026-kernel`. The namespace Image is under `out/experimental-namespaces/arch/arm64/boot/Image`.

## Verify before installing

Use the Image and the complete vendor module sets from the same firmware. Include both vendor_dlkm and vendor boot ramdisk modules, stored privately.

```bash
python3 scripts/verify-kmi.py --symvers <namespace-build-output>/Module.symvers \
    --include-module-exports <private-vendor-module-paths>
bash tests/test-namespaces-vm.sh <namespace-Image>
```

The VM test requires the qemu-system-arm package. It creates an ARM64 guest and checks that a child starts as PID 1 in new namespaces. See the [verified results](baseline-compatibility.md) and [installation and recovery procedure](recovery.md).

For offline K3s networking development, `JOBS=8 bash scripts/build-stock.sh --namespaces-vxlan` adds only VXLAN to the namespace profile. The candidate passed the vendor CRC audit and created a VXLAN link in QEMU. Device boot and cross-node pod networking are pending.

For PID limits, `JOBS=8 bash scripts/build-stock.sh --namespaces-pids` builds an experimental image under `out/experimental-namespaces-pids`. On the pinned GKI configuration it replaces the final cgroup subsystem, legacy `net_prio`, with `pids`. This keeps the subsystem count and the IDs of the other controllers fixed. The test phone on firmware `W1WEOS36.48-22-3-3-4-2` had no `net_prio` mount. This profile removes that controller.

Changing the configuration alone also changes the subsystem enum and removes two networking structure members. The profile applies [a source patch](../patches/pids-legacy-slot.patch) to retain the original enum and members while registering `pids` in that slot. The patched source is isolated from the baseline and the manifest records the patch hash.

The candidate passed the versioned-import audit for all 197 `vendor_dlkm` and 202 early-boot modules on the tested firmware. It preserved every shared export CRC. BTF layouts for `css_set`, `cgroup`, `sock_cgroup_data`, `net_device`, and `netprio_map` matched the namespace baseline. In ARM64 QEMU, the candidate passed the namespace smoke test and returned `EAGAIN` when a process at its `pids.max` limit tried to create a child.

The candidate booted on the test phone from slot A. The flashed bytes matched the candidate, SELinux stayed enforcing, root worked, and the same 360 modules loaded with no sampled module loader warnings. Android exposed `pids` on cgroup v2. A disposable child cgroup with `pids.max=1` rejected process creation with `EAGAIN` and incremented `pids.events`. The test removed the child and restored the original controller delegation. All 17 checks in the Debian regression suite passed. The full hardware checklist remains pending.

Repeat the module audit with the command above. Run `bash tests/test-namespaces-vm.sh <pids-Image> --pids` to check PID limit enforcement before packaging a boot image.

`JOBS=12 bash scripts/build-stock.sh --namespaces-pids-vxlan` combines the PID controller patch and built-in VXLAN in a separate output directory. In addition to the module audit and PID test, run `bash tests/test-vxlan-vm.sh <combined-Image> <Debian-rootfs.tar.gz> <ARM64-deb-directory>` with the Debian `iproute2` and `iputils-ping` packages and their missing dependencies. This test sends packets in both directions over VXLAN between two namespaces in one ARM64 VM.

The combined build passed the audit for all 399 stock vendor modules, preserved every shared export CRC, and passed the namespace, PID-limit, and bidirectional VXLAN probes in QEMU. It booted on slot A with SELinux enforcing, all 360 previously loaded modules, and no sampled module loader warnings. The phone passed the PID-limit probe, the two-namespace VXLAN packet test, and all 17 Debian regression checks.

`--namespaces-pids-vxlan-bridge` is a separate offline profile for bridge netfilter. It retains the stock skb extension IDs and layout while adding storage for the bridge extension. The optional `--bridge-netfilter` mode of the VM test also requires the Debian `iptables` package and its dependencies. It checks that an IPv4 forwarding rule blocks matching bridged packets and that traffic returns when the rule is removed.

`--namespaces-pids-vxlan-cfs` combines PID limits, built-in VXLAN, and CFS bandwidth CPU quotas. It stores CFS bandwidth state outside the vendor-visible scheduler structures, preserving 100% of the 15,422 exported kernel symbol CRCs and passing the vendor module audit for all 399 stock modules. The build was compiled with full production LTO and Clang CFI (`CONFIG_LTO_CLANG_FULL=y`, `CONFIG_CFI_CLANG=y`).

The candidate booted on slot A on the test phone (`W1WEOS36.48-22-3-3-4-2`). SELinux remained enforcing, all 360 vendor modules loaded with zero module loader warnings, and `k3s check-config` verified `CONFIG_CFS_BANDWIDTH: enabled`. Hardware validation via `tests/test-cfs-phone.sh` configured a 10% CPU quota (10,000 us per 100,000 us period) across two busy workers pinned to separate CPU cores via toybox `taskset`. The test recorded 20 out of 20 throttled periods, accumulating 3.69 seconds of enforced throttling time. All 17 Debian regression checks and bidirectional VXLAN packet tests passed on hardware.
