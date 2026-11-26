#!/usr/bin/env bash
set -euo pipefail

green='\033[0;32m'
red='\033[0;31m'
nocolor='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$REPO_ROOT/turnip_workdir"
INSTALL_DIR="$WORKDIR/install"
NDKVER="android-ndk-r29"
NDK="$WORKDIR/$NDKVER/toolchains/llvm/prebuilt/linux-x86_64/bin"
MIN_API=28
MESA_COMMIT="${MESA_COMMIT:-}"

log() { echo -e "${green}$*${nocolor}"; }
die() { echo -e "${red}$*${nocolor}" >&2; exit 1; }

check_deps() {
    local deps="git meson ninja unzip curl flex bison zip glslangValidator python3"
    for dep in $deps; do
        command -v "$dep" >/dev/null 2>&1 || die "Falta a dependência: $dep"
    done
}

prepare_workdir() {
    mkdir -p "$WORKDIR"
    if [ ! -d "$WORKDIR/$NDKVER" ]; then
        log "Baixando Android NDK r29..."
        curl -fsSL "https://dl.google.com/android/repository/${NDKVER}-linux.zip" -o "$WORKDIR/${NDKVER}-linux.zip"
        unzip -q "$WORKDIR/${NDKVER}-linux.zip" -d "$WORKDIR"
    fi

    rm -rf "$WORKDIR/mesa"
    mkdir -p "$WORKDIR/mesa"
    git -C "$WORKDIR/mesa" init -q
    git -C "$WORKDIR/mesa" remote add origin https://gitlab.freedesktop.org/mesa/mesa.git

    if [ -n "$MESA_COMMIT" ]; then
        log "Buscando Mesa fixado em $MESA_COMMIT..."
        git -C "$WORKDIR/mesa" fetch -q --depth=1 origin "$MESA_COMMIT"
    else
        log "Buscando Mesa main..."
        git -C "$WORKDIR/mesa" fetch -q --depth=1 origin refs/heads/main
    fi
    git -C "$WORKDIR/mesa" checkout -q --detach FETCH_HEAD
}

apply_patch() {
    local patch_file="$REPO_ROOT/patches/$1"
    log "Aplicando $1..."
    git apply --check "$patch_file"
    git apply "$patch_file"
}

apply_unified_patches() {
    local script patch_file

    apply_patch a8xx/0001-device-compatibility.patch
    for script in a8xx/apply_a8xx_gpus.py a8xx/a8xx_gpu_ids.py \
                  a7xx/apply_a7xx_gen1_quirks.py \
                  android/fix_gralloc_flushall.py android/add_aimapper_gralloc.py \
                  android/add_ubwc_swapchain_usage.py; do
        python3 -B "$REPO_ROOT/patches/$script"
    done

    for patch_file in "$REPO_ROOT"/patches/a8xx/mesh-and-compute/*.patch; do
        apply_patch "a8xx/mesh-and-compute/$(basename "$patch_file")"
    done
    apply_patch a8xx/0002-scope-pipeline-and-mesh-to-a8xx.patch
    apply_patch a7xx/0001-oneui-ubwc-hint.patch
    apply_patch a6xx/0001-revert-d32s8-late-z-workaround.patch
    apply_patch a6xx/0002-kgsl-context-recovery.patch
    apply_patch common/tu-vauzi-mutable-ubwc.patch
    python3 -B "$REPO_ROOT/patches/a8xx/restore_gen8_profiles.py"

    for script in a8xx/apply_a8xx_cat4_rpt.py a8xx/a8xx_resolve_cr_cntl.py \
                  a8xx/a8xx_lrz_color_mask.py; do
        python3 -B "$REPO_ROOT/patches/$script"
    done

    grep -Fq 'U_GRALLOC_TYPE_AIMAPPER' src/util/u_gralloc/u_gralloc.h
    grep -Fq 'name="Adreno (TM) 825"' src/freedreno/common/freedreno_devices.py
    grep -Fq '0x44041430' src/freedreno/common/freedreno_devices.py
    grep -Fq '0x44051431' src/freedreno/common/freedreno_devices.py
    grep -Fq 'vk_memory_budget_used(physical_device->memory_budget, 0)' src/freedreno/vulkan/tu_device.cc
    python3 -m py_compile src/freedreno/common/freedreno_devices.py
}

apply_android_ndk_fixes() {
    log "Aplicando fixes Android/NDK r29..."
    sed -i 's/typedef const native_handle_t\* buffer_handle_t;/typedef void* buffer_handle_t;/g' include/android_stub/cutils/native_handle.h || true
    sed -i 's/, hnd->handle/, (void *)hnd->handle/g' src/util/u_gralloc/u_gralloc_fallback.c || true
    sed -i -E 's/([a-z_]+)->handle->/((const native_handle_t *)\1->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i 's/anb->handle->/((const native_handle_t *)anb->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i "/-Werror=gnu-empty-initializer/d" meson.build || true
}

build_android() {
    local cver=36
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || cver=35
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || cver=34
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || die "Clang Android aarch64 não encontrado"

    mkdir -p "$WORKDIR/bin"
    ln -sf "$NDK/clang" "$WORKDIR/bin/cc"
    ln -sf "$NDK/clang++" "$WORKDIR/bin/c++"

    export PATH="$WORKDIR/bin:$NDK:$PATH"
    export CC=clang
    export CXX=clang++
    export AR=llvm-ar
    export RANLIB=llvm-ranlib
    export STRIP=llvm-strip
    export OBJDUMP=llvm-objdump
    export OBJCOPY=llvm-objcopy
    export LDFLAGS="-fuse-ld=lld"
    export CFLAGS="-D__ANDROID__ -Wno-error -Wno-error=gnu-empty-initializer -Wno-gnu-empty-initializer -Wno-deprecated-declarations -Wno-incompatible-pointer-types-discards-qualifiers -Wno-incompatible-pointer-types"
    export CXXFLAGS="-D__ANDROID__ -Wno-error -Wno-error=gnu-empty-initializer -Wno-gnu-empty-initializer -Wno-deprecated-declarations -Wno-incompatible-pointer-types-discards-qualifiers -Wno-incompatible-pointer-types"

    cat > android-aarch64.txt <<EOF
[binaries]
ar = '$NDK/llvm-ar'
c = ['$NDK/aarch64-linux-android${cver}-clang']
cpp = ['$NDK/aarch64-linux-android${cver}-clang++', '-fno-exceptions', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '--start-no-unused-arguments', '-static-libstdc++', '--end-no-unused-arguments']
c_ld = '$NDK/ld.lld'
cpp_ld = '$NDK/ld.lld'
strip = '$NDK/llvm-strip'
pkg-config = ['env', 'PKG_CONFIG_LIBDIR=$NDK/pkg-config', '/usr/bin/pkg-config']

[host_machine]
system = 'android'
cpu_family = 'aarch64'
cpu = 'armv8'
endian = 'little'
EOF

    cat > native.txt <<EOF
[build_machine]
c = ['clang']
cpp = ['clang++']
ar = 'llvm-ar'
strip = 'llvm-strip'
c_ld = 'ld.lld'
cpp_ld = 'ld.lld'
system = 'linux'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
EOF

    local build_dir="build-android-aarch64"
    rm -rf "$build_dir" "$INSTALL_DIR"

    meson setup "$build_dir" \
        --cross-file android-aarch64.txt \
        --native-file native.txt \
        --prefix "$INSTALL_DIR" \
        --libdir lib \
        -Dbuildtype=release \
        -Dstrip=true \
        -Dplatforms=android \
        -Dvideo-codecs= \
        -Dplatform-sdk-version=36 \
        -Dandroid-stub=true \
        -Dgallium-drivers= \
        -Dvulkan-drivers=freedreno \
        -Dvulkan-beta=true \
        -Dfreedreno-kmds=kgsl \
        -Degl=disabled \
        -Dandroid-libbacktrace=disabled

    ninja -C "$build_dir" install

    [ -f "$INSTALL_DIR/lib/libvulkan_freedreno.so" ] || die "libvulkan_freedreno.so não foi gerada"
}

package_driver() {
    local mesa_sha header_version output_dir archive
    mesa_sha="$(git rev-parse HEAD)"
    header_version="$(awk '$2 == "VK_HEADER_VERSION" {print $3}' include/vulkan/vulkan_core.h)"
    [[ "$header_version" =~ ^[0-9]+$ ]] || die "VK_HEADER_VERSION inválido"
    output_dir="$INSTALL_DIR/lib"
    archive="$WORKDIR/Turnip_v27.0.0-R3.zip"

    python3 - "$mesa_sha" "$header_version" "$MIN_API" "$output_dir/meta.json" <<'PYMETA'
import json
import sys
from pathlib import Path

commit, header_version, min_api, output = sys.argv[1:]
meta = {
    "schemaVersion": 1,
    "name": "Turnip v27.0.0-R3",
    "description": f"Mesa {commit}",
    "author": "StevenMXZ",
    "packageVersion": "R2",
    "vendor": "Mesa",
    "driverVersion": f"Vulkan 1.4.{header_version}",
    "minApi": int(min_api),
    "libraryName": "libvulkan_freedreno.so",
}
Path(output).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PYMETA

    rm -f "$archive"
    (cd "$output_dir" && zip -9 -q "$archive" libvulkan_freedreno.so meta.json)
    unzip -tq "$archive"
    log "Gerado: $archive"
}

main() {
    check_deps
    prepare_workdir
    cd "$WORKDIR/mesa"

    log "Mesa: $(git rev-parse HEAD)"
    apply_unified_patches
    apply_android_ndk_fixes
    build_android
    package_driver
}

main "$@"
