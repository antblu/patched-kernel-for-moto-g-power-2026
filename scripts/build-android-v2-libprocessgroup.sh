#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
aosp_dir=${AOSP_DIR:-"$HOME/.cache/vegas26-aosp-android16"}
out_dir=${OUT_DIR:-out-vegas26-narrow}
jobs=${JOBS:-12}

if [[ ! -d "$aosp_dir/system/core/libprocessgroup" ]]; then
    echo "Expected AOSP tree at $aosp_dir" >&2
    exit 1
fi

patches=(
    android16-process-domain-attributes.patch
    android16-threaded-group-cleanup.patch
    android16-threaded-group-placement.patch
    android16-process-group-attachment.patch
    android16-isolated-process-attach-retry.patch
    android16-cgroup-map-vanished-proc.patch
)

cd "$aosp_dir"
if git -C system/core diff --quiet libprocessgroup; then
    for name in "${patches[@]}"; do
        patch_file="$repo_root/patches/$name"
        git -C system/core apply --check "$patch_file"
        git -C system/core apply "$patch_file"
    done
elif ! git -C system/core apply --reverse --check "$repo_root/patches/android16-cgroup-map-vanished-proc.patch" 2>/dev/null; then
    patch_file="$repo_root/patches/android16-cgroup-map-vanished-proc.patch"
    git -C system/core apply --check "$patch_file"
    git -C system/core apply "$patch_file"
fi

dirs=(
    - Android.bp build/ bionic/ system/core/ system/libbase/ system/logging/
    system/libhidl/ system/libhwbinder/ system/gsid/ system/tools/hidl/
    system/libsysprop/ system/libvintf/ system/sepolicy/ system/selinux/
    system/libziparchive/ system/hardware/interfaces/ system/tools/aidl/
    system/unwinding/ hardware/interfaces/ hardware/libhardware/
    frameworks/hardware/interfaces/ frameworks/native/Android.bp
    frameworks/native/libs/binder/ frameworks/native/headers/
    external/avb/ external/arm-optimized-routines/ external/boringssl/
    external/fmtlib/ external/e2fsprogs/ external/golang-protobuf/
    external/gwp_asan/ external/sqlite/ external/googletest/ external/jsoncpp/
    external/libcxx/ external/libcxxabi/ external/libunwind_llvm/
    external/libcap/ external/libcap-ng/ external/libffi/ external/libxml2/
    external/lz4/ external/pcre/ external/protobuf/ external/selinux/
    external/tinyxml2/ external/zlib/ external/zstd/
    external/icu/Android.bp external/icu/icu4c/ external/icu/android_icu4c/
    external/icu/libicu/ external/icu/libandroidicu/
    external/icu/libandroidicuinit/
    external/google-benchmark/ external/clang/ external/compiler-rt/
    external/llvm-libc/ external/scudo/ external/rust/ prebuilts/build-tools/
    prebuilts/clang/host/linux-x86/ prebuilts/gcc/ prebuilts/rust/
    prebuilts/sdk/ toolchain/pgo-profiles/sampling/
    packages/services/Car/teams/Android.bp
)
export PRODUCT_SOURCE_ROOT_DIRS="${dirs[*]}"

python3 - <<'PY'
import os
from pathlib import Path

soong_cfg = Path("build/make/core/soong_config.mk")
source = soong_cfg.read_text()
prefix = "$(call add_json_list, SourceRootDirs,"
old, = [line for line in source.splitlines() if line.startswith(prefix)]
new = f"{prefix} {os.environ['PRODUCT_SOURCE_ROOT_DIRS']})"
if old != new:
    soong_cfg.write_text(source.replace(old, new, 1))

aconfig = Path("build/soong/aconfig/all_aconfig_declarations.go")
aconfig_src = aconfig.read_text()
target = "\tfinalizedFlagsFile := android.PathForModuleSrc(ctx, apiSurface.Finalized_flags_file)\n"
guard = target + "\tif finalizedFlagsFile == nil { return }\n"
if guard not in aconfig_src and target in aconfig_src:
    aconfig.write_text(aconfig_src.replace(target, guard))
PY

product="build/make/target/product/aosp_arm64.mk"
setting="PRODUCT_CGROUP_V2_SYS_APP_ISOLATION_ENABLED := true"
if ! grep -Fxq "$setting" "$product"; then
    printf '\n%s\n' "$setting" >> "$product"
fi

export OUT_DIR="$out_dir"
export SOONG_ONLY=true
export ALLOW_MISSING_DEPENDENCIES=true
export TARGET_BUILD_UNBUNDLED=true
export WITH_DEXPREOPT=false
export DISABLE_PREOPT=true
export DISABLE_PREOPT_BOOT_IMAGES=true

set +u
source build/envsetup.sh
lunch aosp_arm64-aosp_current-userdebug
set -u

lib="$out_dir/target/product/generic_arm64/system/lib64/libprocessgroup.so"
m -j"$jobs" "$lib"

baseline="$repo_root/.cache/k3s-active-baseline/libprocessgroup.so"
if [[ -f "$baseline" ]]; then
    python3 "$repo_root/scripts/verify-libprocessgroup-abi.py" "$baseline" "$lib"
fi
sha256sum "$lib"
