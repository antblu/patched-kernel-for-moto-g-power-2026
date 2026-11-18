#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || ! -f $1 || ( $# -eq 2 && $2 != --pids ) ]]; then
    printf 'Usage: bash tests/test-namespaces-vm.sh <ARM64-Image> [--pids]\n' >&2
    exit 2
fi
image=$(realpath -- "$1")
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cache=${KERNEL_BUILD_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/moto-g-power-2026-kernel}
source="$cache/ack-9b2308ac0ad616788fb57ba688aa07f0ff221355"
clang="$cache/clang-5538393cf30cb39da6d53730a9b85f36958230da/bin/clang"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/kbuild"
probe=namespace-init.c
marker=NAMESPACE_SMOKE_PASS
entries=(init)
if [[ ${2:-} == --pids ]]; then
    probe=pids-init.c
    marker=PID_LIMIT_PASS
    mkdir "$scratch/cg"
    entries+=(cg)
fi
make -s -C "$source" O="$scratch/kbuild" ARCH=arm64 \
    INSTALL_HDR_PATH="$scratch/headers" headers_install

"$clang" --target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -static -ffreestanding \
    -fno-stack-protector -O2 -I "$scratch/headers/include" "$project/tests/$probe" -o "$scratch/init"
(cd "$scratch" && printf '%s\n' "${entries[@]}" | cpio --quiet -o -H newc | gzip -n > initramfs.gz)
timeout 120s qemu-system-aarch64 -machine virt -cpu cortex-a57 -m 768M \
    -nodefaults -nic none -display none -monitor none -serial stdio -no-reboot \
    -kernel "$image" -initrd "$scratch/initramfs.gz" \
    -append 'console=ttyAMA0 quiet rdinit=/init panic=-1' | tee "$scratch/console.log"
grep -q "^$marker" "$scratch/console.log"
