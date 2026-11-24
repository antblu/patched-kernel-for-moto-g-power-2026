# Repository Guidelines

## Project structure

This repository builds and validates a custom ARM64 kernel for the Moto G Power 2026 (`vegas26`). The build scripts fetch pinned Android Common Kernel and Clang sources into a local cache. Keep kernel config changes in `configs/fragments/` and source changes in `patches/`. Build, packaging, and Debian setup tools live in `scripts/`. Find Python unit tests, ARM64 QEMU probes, and phone tests in `tests/`. Record build, compatibility, and recovery procedures in `docs/`.

## Build and development

Use Ubuntu 24.04 or Ubuntu under WSL2. Keep kernel sources and build outputs on the Linux filesystem.

- `bash scripts/setup-build-env.sh` installs build dependencies.
- `bash scripts/fetch-sources.sh` downloads and verifies the pinned sources and toolchain.
- `bash scripts/build-stock.sh` builds the GKI reference. Add `--namespaces` for the namespace candidate.
- `pre-commit install` enables staged-file and secret checks.

## Coding style

Use four spaces for Python and new shell blocks. Match surrounding formatting in kernel patches. Name Python test files `test_*.py` and shell probes `test-<feature>-<target>.sh` where the target matters. Keep each kernel config change focused and check that Kconfig resolves the requested options.

## Testing

Run `python3 -m unittest discover -s tests -v` and `for file in scripts/*.sh tests/*.sh; do bash -n "$file" || exit; done` before submitting. For kernel changes, run the relevant ARM64 QEMU probe and use `scripts/verify-kmi.py` to audit both vendor module sets against the candidate. Report build, VM, and hardware results separately. Before a phone test, verify the exact firmware, active slot, image hashes, and rollback path in `docs/recovery.md`.

## Commits and pull requests

Use short imperative subjects, following the history's style, such as “Verify stock boot restore on slot A.” Explain the change, link relevant issues, and report test commands, results, and gaps. Include the firmware and kernel release for compatibility claims. Keep firmware images, partition backups, device identifiers, raw logs, and credentials out of Git. Review the staged diff and run `python3 scripts/check-public-index.py` before pushing.

## K3s lab handoff

- Preserve the phone's verified runtime during lab changes. It uses pure cgroup v2 (`cgroup_no_v1=all,named`), `tini` as PID 1, `cgroupfs` for kubelet and containerd, ext4-backed data (`/var/lib/vegas26-k3s-storage`), SELinux Permissive, `oom_score_adj=-1000` for the runtime, and the `k3s_node` wake lock. Preserve routing priorities 96/97/98/100/101 and the `BACKGROUND_MATCH` exemption for host UID 65532. Keep that UID unassigned to Android packages and services.
- The cluster runs as a fully self-hosted, 3-node HA multi-master control plane directly on-device across the three physical Moto G Power 2026 phones with embedded etcd (`vegas26-phone-1`: `100.64.0.2`, `vegas26-phone-2`: `100.64.0.13`, `vegas26-node-0`: `100.64.0.7`). All three nodes hold roles `control-plane,etcd`. The WSL control plane services (`vegas26-k3s-server.service`, `vegas26-tunnel-watchdog.service`) are permanently decommissioned; WSL acts strictly as a remote `kubectl` client over Tailscale (`https://100.64.0.2:6443`).
- Node interconnect runs over a supervised `tailscaled` mesh authenticated to Headscale (`https://vpn.antblu.net`) on `tailscale0` (MTU 1280, Flannel VXLAN MTU 1230). WireGuard `wg-k3s` and ADB reverse forwarding dependencies were decommissioned.
- CoreDNS runs with 3 replicas distributed across all three physical phones with anti-affinity, configured with `securityContext.runAsUser: 0` to avoid Android BPF socket restrictions on non-root UIDs, and `--disable coredns` set in K3s `config.yaml` to prevent addon overwrite. CoreDNS includes upstream/Headscale mapping (`10.30.0.200 rancher.antblu.net`). Rancher `cattle-cluster-agent`, `cattle-fleet-system/fleet-agent`, and `rancher-webhook` run directly on-cluster.
- The November 21, 2026 HA validation verified all 3 nodes Ready, embedded etcd quorum healthy across all 3 peers, full mesh networking (`K3S_CROSS_NODE_NETWORK_PASS` between Phone 1 <-> Phone 2, Phone 1 <-> Node 0, and Phone 2 <-> Node 0 for bidirectional 256 KiB Pod IP & ClusterIP transfers, Service DNS, and NetworkPolicy enforcement), local-path storage persistence (`K3S_STORAGE_PERSISTENCE_PASS`), and execution isolation (`K3S_EXEC_ISOLATION_PASS`) on all 3 phones.
- Recheck live state before making changes. Use the runbook in `docs/k3s-worker-plan.md` for persistent launch, backup paths, verification evidence, and rollback. Keep private keys, tokens, and backup contents out of Git.
