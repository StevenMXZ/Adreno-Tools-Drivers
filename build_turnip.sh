#!/usr/bin/env bash
set -euo pipefail

green='\033[0;32m'
red='\033[0;31m'
nocolor='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="$REPO_ROOT/turnip_workdir"
NDKVER="android-ndk-r29"
NDK="$WORKDIR/$NDKVER/toolchains/llvm/prebuilt/linux-x86_64/bin"
BUILD_VERSION="${BUILD_VERSION:-1.0}"
VARIANT="${VARIANT:-a7xx}"
MESA_COMMIT="${MESA_COMMIT:-}"

REVERT_COMMIT="a70d2af590db192f87b3af01f83a68b450edb4c3"

log() { echo -e "${green}$*${nocolor}"; }
die() { echo -e "${red}$*${nocolor}" >&2; exit 1; }

check_deps() {
    local deps="git meson ninja patchelf unzip curl pip flex bison zip glslangValidator python3 patch"
    for dep in $deps; do
        command -v "$dep" >/dev/null 2>&1 || die "Missing dependency: $dep"
    done
    pip install mako --break-system-packages >/dev/null 2>&1 || true
}

prepare_workdir() {
    mkdir -p "$WORKDIR"
    if [ ! -d "$WORKDIR/$NDKVER" ]; then
        log "Downloading Android NDK r29..."
        curl -sL "https://dl.google.com/android/repository/${NDKVER}-linux.zip" -o "$WORKDIR/${NDKVER}-linux.zip"
        unzip -q "$WORKDIR/${NDKVER}-linux.zip" -d "$WORKDIR"
    fi

    rm -rf "$WORKDIR/mesa"
    mkdir -p "$WORKDIR/mesa"
    git -C "$WORKDIR/mesa" init -q
    git -C "$WORKDIR/mesa" remote add origin https://gitlab.freedesktop.org/mesa/mesa.git

    if [ -n "$MESA_COMMIT" ]; then
        log "Fetching pinned Mesa at $MESA_COMMIT..."
        git -C "$WORKDIR/mesa" fetch -q --depth=1 origin "$MESA_COMMIT"
    else
        log "Fetching Mesa main..."
        git -C "$WORKDIR/mesa" fetch -q --depth=1 origin refs/heads/main
    fi
    git -C "$WORKDIR/mesa" checkout -q --detach FETCH_HEAD
}

revert_d32s8_commit() {
    log "A7xx: reverting workaround D32S8 EARLY_Z_LATE_Z..."
    if ! git cat-file -e "${REVERT_COMMIT}^{commit}" 2>/dev/null; then
        git fetch -q --depth=2 origin "$REVERT_COMMIT"
    fi
    git revert --no-commit "$REVERT_COMMIT" || {
        git revert --abort 2>/dev/null || true
        git reset --hard HEAD
        die "Falha ao reverter $REVERT_COMMIT"
    }
}

apply_a7xx_base() {
    revert_d32s8_commit

    log "A7xx: applying has_early_preamble=False..."
    if ! grep -A20 'a7xx_gen1 = GPUProps(' src/freedreno/common/freedreno_devices.py | grep -q 'has_early_preamble = False'; then
        sed -i '/a7xx_gen1 = GPUProps(/a \\        has_early_preamble = False,' src/freedreno/common/freedreno_devices.py
    fi
    python3 -m py_compile src/freedreno/common/freedreno_devices.py
}

apply_oneui_glitch() {
    log "A7xx OneUI: applying 8g2_ui_glitch.patch..."
    patch -p1 --forward < "$REPO_ROOT/8g2_ui_glitch.patch"
}

apply_patchs2_a8xx() {
    log "A8xx Patchs2: applying KGSL common fixes..."
    bash "$REPO_ROOT/patches/patchs2/common/apply_common.sh" "$PWD"

    log "A8xx Patchs2: applying gen8 stack..."
    patch -p1 -N --fuzz=4 --no-backup-if-mismatch < "$REPO_ROOT/patches/patchs2/a8xx_gen8.patch"

    log "A8xx Patchs2: shared memory 32 KiB -> 64 KiB..."
    python3 "$REPO_ROOT/patches/patchs2/a8xx_shared_mem.py"

    log "A8xx Patchs2: applying A840v2..."
    python3 "$REPO_ROOT/patches/patchs2/a840v2.py"
}

apply_patchs1_android_scripts() {
    log "A8xx Patchs1: applying Android/Bionic recipe..."
    local scripts=(
        fix_gralloc_flushall.py
        fix_a8xx_dev_info.py
        apply_a8xx_gpus.py
        apply_a7xx_gen1_quirks.py
        apply_a7xx_gen2_ubwc_hint.py
        add_aimapper_gralloc.py
        add_ubwc_swapchain_usage.py
    )
    local script
    for script in "${scripts[@]}"; do
        log "Patchs1: $script"
        python3 "$REPO_ROOT/patches/patchs1/android/$script"
    done

    log "Patchs1: using balanced variant..."
    python3 "$REPO_ROOT/patches/patchs1/android/apply_balance_variant.py"
}

apply_patchs1_extra_patches() {
    log "A8xx Patchs1: applying extra patchset 0001-0006..."
    local patch_file
    local count=0
    for patch_file in "$REPO_ROOT"/patches/patchs1/000*.patch; do
        [ -f "$patch_file" ] || continue
        log "Checking $(basename "$patch_file")..."
        if ! git apply --check "$patch_file"; then
            git apply --check --verbose "$patch_file" || true
            die "Patchs1 patch does not apply cleanly: $(basename "$patch_file")"
        fi
        git apply "$patch_file"
        count=$((count + 1))
    done
    [ "$count" -eq 6 ] || die "Expected 6 Patchs1 patches, found $count"
}

apply_android_ndk_fixes() {
    log "Applying Android/NDK r29 fixes..."
    sed -i 's/typedef const native_handle_t\* buffer_handle_t;/typedef void* buffer_handle_t;/g' include/android_stub/cutils/native_handle.h || true
    sed -i 's/, hnd->handle/, (void *)hnd->handle/g' src/util/u_gralloc/u_gralloc_fallback.c || true
    sed -i -E 's/([a-z_]+)->handle->/((const native_handle_t *)\1->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i 's/anb->handle->/((const native_handle_t *)anb->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i "/-Werror=gnu-empty-initializer/d" meson.build || true
}

configure_variant() {
    case "$VARIANT" in
        a7xx)
            apply_a7xx_base
            ;;
        a7xx-oneui)
            apply_a7xx_base
            apply_oneui_glitch
            ;;
        a8xx-patchs2)
            apply_patchs2_a8xx
            ;;
        a8xx-patchs1)
            apply_patchs1_android_scripts
            apply_patchs1_extra_patches
            log "A8xx Patchs1: applying KGSL zero-timeout poll fix..."
            local poll_patch="$REPO_ROOT/patches/patchs2/common/kgsl-zero-timeout-poll.patch"
            if ! git apply --check "$poll_patch"; then
                die "KGSL zero-timeout poll patch does not apply cleanly"
            fi
            git apply "$poll_patch"
            grep -Fq 'kgsl_timestamp_retired(fd, context_id, timestamp) ? VK_SUCCESS : VK_TIMEOUT' src/freedreno/vulkan/tu_knl_kgsl.cc ||
                die "KGSL zero-timeout poll fix not found in final source"
            ;;
        *)
            die "Invalid VARIANT: $VARIANT"
            ;;
    esac
}

build_android() {
    local cver=36
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || cver=35
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || cver=34
    [ -f "$NDK/aarch64-linux-android${cver}-clang" ] || die "Android aarch64 Clang not found"

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
    local output_dir="/tmp/turnip-$VARIANT"
    rm -rf "$build_dir" "$output_dir"

    meson setup "$build_dir"         --cross-file android-aarch64.txt         --native-file native.txt         --prefix "$output_dir"         -Dbuildtype=release         -Dstrip=true         -Dplatforms=android         -Dvideo-codecs=         -Dplatform-sdk-version=36         -Dandroid-stub=true         -Dgallium-drivers=         -Dvulkan-drivers=freedreno         -Dvulkan-beta=true         -Dfreedreno-kmds=kgsl         -Degl=disabled         -Dandroid-libbacktrace=disabled

    ninja -C "$build_dir" install

    [ -f "$output_dir/lib/libvulkan_freedreno.so" ] || die "libvulkan_freedreno.so was not generated"
}

package_variant() {
    local mesa_short
    mesa_short="$(git rev-parse --short=12 HEAD)"

    local pretty_name desc suffix
    case "$VARIANT" in
        a7xx)
            pretty_name="Turnip A7xx"
            desc="StevenMXZ A7xx Android/Bionic — revert D32S8 + has_early_preamble=False"
            suffix="A7xx"
            ;;
        a7xx-oneui)
            pretty_name="Turnip A7xx OneUI Glitch"
            desc="StevenMXZ A7xx Android/Bionic + OneUI 8g2 UI glitch fix"
            suffix="A7xx-OneUI-Glitch"
            ;;
        a8xx-patchs2)
            pretty_name="Turnip A8xx Patchs2"
            desc="Patchs2 A8xx Android/Bionic recipe: KGSL common + turnip/gen8 + 64KiB shared memory"
            suffix="A8xx-Patchs2"
            ;;
        a8xx-patchs1)
            pretty_name="Turnip A8xx Patched Patchs1"
            desc="Patchs1 Android/Bionic balanced recipe + extra 0001-0006 A8xx patchset"
            suffix="A8xx-Patched-Patchs1"
            ;;
    esac

    local output_dir="/tmp/turnip-$VARIANT"
    cd "$output_dir/lib"

    cat > meta.json <<EOF
{
  "schemaVersion": 1,
  "name": "$pretty_name",
  "description": "$desc — Mesa $mesa_short",
  "author": "StevenMXZ",
  "packageVersion": "$BUILD_VERSION",
  "vendor": "Mesa",
  "driverVersion": "Mesa-$mesa_short",
  "minApi": 28,
  "libraryName": "libvulkan_freedreno.so"
}
EOF

    local zip_name="Turnip_${suffix}_V${BUILD_VERSION}_${mesa_short}.zip"
    rm -f "$WORKDIR/$zip_name"
    zip -9 -q "$WORKDIR/$zip_name" libvulkan_freedreno.so meta.json
    log "Generated: $WORKDIR/$zip_name"
}

main() {
    check_deps
    prepare_workdir
    cd "$WORKDIR/mesa"

    log "Mesa: $(git rev-parse HEAD)"
    log "Variant: $VARIANT"

    configure_variant
    apply_android_ndk_fixes
    build_android
    package_variant
}

main "$@"
