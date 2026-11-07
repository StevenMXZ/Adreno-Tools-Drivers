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

# tu/a6xx: Work around D32S8 EARLY_Z_LATE_Z hang
REVERT_COMMIT="a70d2af590db192f87b3af01f83a68b450edb4c3"

log() { echo -e "${green}$*${nocolor}"; }
die() { echo -e "${red}$*${nocolor}" >&2; exit 1; }

check_deps() {
    local deps="git meson ninja patchelf unzip curl pip flex bison zip glslangValidator python3 patch"
    for dep in $deps; do
        command -v "$dep" >/dev/null 2>&1 || die "Falta a dependência: $dep"
    done
    pip install mako --break-system-packages >/dev/null 2>&1 || true
}

prepare_workdir() {
    mkdir -p "$WORKDIR"
    if [ ! -d "$WORKDIR/$NDKVER" ]; then
        log "Baixando Android NDK r29..."
        curl -sL "https://dl.google.com/android/repository/${NDKVER}-linux.zip" -o "$WORKDIR/${NDKVER}-linux.zip"
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

revert_d32s8_commit() {
    log "A7xx: revertendo workaround D32S8 EARLY_Z_LATE_Z..."
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

    log "A7xx: aplicando has_early_preamble=False..."
    if ! grep -A20 'a7xx_gen1 = GPUProps(' src/freedreno/common/freedreno_devices.py | grep -q 'has_early_preamble = False'; then
        sed -i '/a7xx_gen1 = GPUProps(/a \\        has_early_preamble = False,' src/freedreno/common/freedreno_devices.py
    fi
    python3 -m py_compile src/freedreno/common/freedreno_devices.py
}

apply_oneui_glitch() {
    log "A7xx OneUI: aplicando 8g2_ui_glitch.patch..."
    patch -p1 --forward < "$REPO_ROOT/8g2_ui_glitch.patch"
}

apply_Gen8_a8xx() {
    log "A8xx Gen8: aplicando whitebelyash turnip/gen8 stack..."
    patch -p1 -N --fuzz=4 --no-backup-if-mismatch < "$REPO_ROOT/patches/patchsv2/a8xx_gen8.patch"

    log "A8xx Gen8: shared memory 32 KiB -> 64 KiB..."
    python3 "$REPO_ROOT/patches/patchsv2/a8xx_shared_mem.py"

    # Compatibility Android gralloc/UBWC support is already ported in our
    # Patched Android recipe. Reuse the same implementation for Gen8.
    log "A8xx Gen8: enabling modern Qualcomm gralloc and UBWC..."
    python3 "$REPO_ROOT/patches/patchsv1/android/fix_gralloc_flushall.py"
    python3 "$REPO_ROOT/patches/patchsv1/android/add_aimapper_gralloc.py"
    python3 "$REPO_ROOT/patches/patchsv1/android/add_ubwc_swapchain_usage.py"
}

apply_Patched_android_scripts() {
    log "A8xx Patched: aplicando recipe Android/Bionic production..."
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
        log "Patched: $script"
        python3 "$REPO_ROOT/patches/patchsv1/android/$script"
    done

    log "Patched: usando variante balanced..."
    python3 "$REPO_ROOT/patches/patchsv1/android/apply_balance_variant.py"
}

apply_Patched_extra_patches() {
    log "A8xx Patched: aplicando patchset extra 0001-0005..."
    local patch_file
    local count=0
    for patch_file in "$REPO_ROOT"/patches/patchsv1/000*.patch; do
        [ -f "$patch_file" ] || continue
        log "Verificando $(basename "$patch_file")..."
        if ! git apply --check "$patch_file"; then
            git apply --check --verbose "$patch_file" || true
            die "Patch Patched não aplica limpo: $(basename "$patch_file")"
        fi
        git apply "$patch_file"
        count=$((count + 1))
    done
    [ "$count" -eq 5 ] || die "Esperados 5 patches Patched, encontrados $count"
}

# Compatibility-derived A8xx register adjustments. Existing Patched scope.
# These are not the A8xx-17 Turnip-Z mutable/BGRA patches.
apply_Compatibility_Patched_registers_only() {
    log "A8xx Patched: applying Compatibility A8xx register adjustments..."
    local dd="$REPO_ROOT/patches/patchsv3/scripts"

    python3 "$dd/a8xx_resolve_cr_cntl.py"
    # Disabled: on A830 the hysteresis registers reduced DriverLab card FPS by
    # ~6% without a demonstrated correctness gain (Gen8 4ccd4e9).
    python3 "$dd/a8xx_lrz_color_mask.py"

    grep -Fq 'A6XXRegs.REG_A8XX_RB_RESOLVE_CR_CNTL' src/freedreno/common/freedreno_devices.py \
        || die "A8xx A8xx: RB_RESOLVE_CR_CNTL preamble missing"
    grep -Fq 'GRAS_LRZ_COLOR_COMP_MASK(CHIP, .dword = lrz_color_comp_mask)' src/freedreno/vulkan/tu_pipeline.cc \
        || die "A8xx A8xx: LRZ color mask missing"
}

# The Gen8 gen8 stack enables double-threadsize, which regressed compute
# subgroup correctness on A830; Patched keeps the Mesa default. Verify both.
apply_a8xx_subgroup_fix() {
    log "A8xx: retaining Mesa subgroup correctness (double_threadsize=false)..."
    python3 "$REPO_ROOT/patches/a8xx/a8xx_no_double_threadsize.py"
}

# Gen8's executable-specific SSBO overrides. Add to both requested A8xx builds.
# These are per-game rules, not a global change to Turnip.
apply_a8xx_game_profiles() {
    log "A8xx: installing game-specific SSBO emulation profiles..."
    python3 "$REPO_ROOT/patches/a8xx/game_ssbo_profiles.py"
}

# Compatibility Android fixes, scoped to A8xx Gen8 and A8xx Patched only.
# Preserve the existing variant-specific GPU recipes and Patched patches.
apply_Compatibility_a8xx() {
    log "A8xx: applying Compatibility compatibility fixes (without KGSL PWR_MAX)..."
    local dd="$REPO_ROOT/patches/Compatibility"

    # The two A8xx recipes already supply A825 and most A810/A829 settings;
    # add only missing KGSL aliases, plus A845/A850, not a duplicate GPU stack.
    python3 "$dd/scripts/a8xx_gpu_ids.py"
    python3 "$dd/scripts/apply_a8xx_cat4_rpt.py"
    python3 "$dd/scripts/process_heap_usage.py"

    # These source changes are shared by all Mesa legs; only the two A8xx
    # variants opt in. Reject a drifted patch instead of silently shipping it.
    local patch_file target marker
    for patch_file in \
        "$dd/lrz/0001-tu-a8xx-lrz-reset-cntl-after-flush.patch" \
        "$dd/nir/0001-nir-lower-explicit-io-keep-32bit-offset-wrap.patch" \
        "$dd/fdl/0001-fdl-a8xx-buffer-num-elements.patch"; do
        case "$patch_file" in
            */lrz/*)
                target="src/freedreno/vulkan/tu_lrz.cc"
                marker='tu6_write_lrz_cntl<CHIP>(cmd, cs, {});'
                ;;
            */nir/*)
                target="src/compiler/nir/nir_lower_explicit_io.c"
                marker='offset = nir_iand_imm(b, offset, UINT32_MAX >> shift);'
                ;;
            */fdl/*)
                target="src/freedreno/fdl/fd6_view.cc"
                marker='A8XX_TEX_MEMOBJ_2_NUM_ELEMENTS(elements)'
                ;;
        esac

        if git apply --check "$patch_file"; then
            log "Compatibility: applying $(basename "$patch_file")"
            git apply "$patch_file"
        elif grep -Fq "$marker" "$target"; then
            log "Compatibility: $(basename "$patch_file") already present in Mesa"
        else
            git apply --check --verbose "$patch_file" || true
            die "Compatibility: patch did not apply and upstream fix is absent: $patch_file"
        fi
    done

    # Existing Patched IMapper/UBWC changes also run for Gen8.
    grep -Fq 'u_gralloc_aimapper.c' src/util/u_gralloc/meson.build \
        || die "A8xx: IMapper5 backend not built"
    grep -Fq 'U_GRALLOC_TYPE_AIMAPPER' src/util/u_gralloc/u_gralloc.h \
        || die "A8xx: IMapper5 backend enum missing"
    grep -Fq 'ahb_vendor_usage_compressed = 0x10000000ull' src/freedreno/vulkan/tu_device.cc \
        || die "A8xx: vendor UBWC allocation usage missing"
    grep -Fq 'UBWC flag detection - bypass legacy gmsm magic check for A8XX/A840.' src/util/u_gralloc/u_gralloc_fallback.c \
        || die "A8xx: bounds-checked Qualcomm gralloc UBWC detection missing"
    grep -Fq 'tu_process_heap_used' src/freedreno/vulkan/tu_device.cc \
        || die "A8xx: process-wide memory budget fix missing"
    grep -Fq '0x44041430' src/freedreno/common/freedreno_devices.py \
        || die "A8xx: A845 ID missing"
    grep -Fq '0x44051431' src/freedreno/common/freedreno_devices.py \
        || die "A8xx: A850 ID missing"
}

# MR !44838 (Mesa main, 2026-10-08):
# 1da50a1b: correctly merge KGSL timestamp syncobjs and sync-file fds.
# e984ef29: poll retired GPU timestamps for zero-timeout checks without blocking.
# These fixes are upstream. Never apply the obsolete local zero-timeout patch.
verify_mesa_mr_44838() {
    local kgsl="src/freedreno/vulkan/tu_knl_kgsl.cc"
    log "Common: verifying upstream Mesa MR !44838 KGSL fixes..."

    [ -f "$kgsl" ] || die "Missing $kgsl"
    grep -Fq 'kgsl_syncobj_merge(struct tu_device *device' "$kgsl" \
        || die "Mesa is missing MR !44838 mixed timestamp/sync-file merge fix (1da50a1b)"
    grep -Fq 'return kgsl_poll_timestamp(device, context_id, timestamp);' "$kgsl" \
        || die "Mesa is missing MR !44838 zero-timeout nonblocking poll fix (e984ef29)"
    log "Mesa MR !44838: both upstream KGSL fixes verified"
}

apply_common_turnip_patches() {
    log "Common: applying sample-shading interpolation gate..."
    local sample_patch="$REPO_ROOT/patches/common/tu-sample-shading-gate.patch"
    if ! git apply --check "$sample_patch"; then
        git apply --check --verbose "$sample_patch" || true
        die "Common patch tu-sample-shading-gate.patch did not apply cleanly"
    fi
    git apply "$sample_patch"

    local shader_file="src/freedreno/vulkan/tu_shader.cc"
    grep -Fq 'if (nir->info.stage == MESA_SHADER_FRAGMENT && key->force_sample_interp &&' "$shader_file" \
        || die "Common sample-shading patch did not update the pipeline gate"
    grep -Fq '       nir->info.fs.uses_sample_shading) {' "$shader_file" \
        || die "Common sample-shading patch did not preserve static sample-shading usage"
}

apply_android_ndk_fixes() {
    log "Aplicando fixes Android/NDK r29..."
    sed -i 's/typedef const native_handle_t\* buffer_handle_t;/typedef void* buffer_handle_t;/g' include/android_stub/cutils/native_handle.h || true
    sed -i 's/, hnd->handle/, (void *)hnd->handle/g' src/util/u_gralloc/u_gralloc_fallback.c || true
    sed -i -E 's/([a-z_]+)->handle->/((const native_handle_t *)\1->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i 's/anb->handle->/((const native_handle_t *)anb->handle)->/g' src/vulkan/runtime/vk_android.c || true
    sed -i "/-Werror=gnu-empty-initializer/d" meson.build || true
}

clean_a7xx_driver_names() {
    find src/freedreno/vulkan -type f -name "*.c*" -exec sed -i         's/"Turnip Adreno (TM) %s[^"]*"/"Turnip Adreno (TM) %s%.0s"/g' {} + || true
    find src/freedreno/vulkan -type f -name "*.c*" -exec sed -i         's/"turnip Mesa driver (whitebelyash branch)"/"Turnip"/g' {} + || true
    find src/freedreno/vulkan -type f -name "*.c*" -exec sed -i         's/"turnip Mesa driver"/"Turnip"/g' {} + || true
}

configure_variant() {
    case "$VARIANT" in
        a7xx)
            apply_a7xx_base
            clean_a7xx_driver_names
            ;;
        a7xx-oneui)
            apply_a7xx_base
            apply_oneui_glitch
            clean_a7xx_driver_names
            ;;
        a8xx-gen8)
            revert_d32s8_commit
            apply_Gen8_a8xx
            ;;
        a8xx-patched)
            apply_Patched_android_scripts
            apply_Patched_extra_patches
            apply_Compatibility_Patched_registers_only
            ;;
        *)
            die "VARIANT inválido: $VARIANT"
            ;;
    esac
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
    local output_dir="/tmp/turnip-$VARIANT"
    rm -rf "$build_dir" "$output_dir"

    meson setup "$build_dir"         --cross-file android-aarch64.txt         --native-file native.txt         --prefix "$output_dir"         -Dbuildtype=release         -Dstrip=true         -Dplatforms=android         -Dvideo-codecs=         -Dplatform-sdk-version=36         -Dandroid-stub=true         -Dgallium-drivers=         -Dvulkan-drivers=freedreno         -Dvulkan-beta=true         -Dfreedreno-kmds=kgsl         -Degl=disabled         -Dandroid-libbacktrace=disabled

    ninja -C "$build_dir" install

    [ -f "$output_dir/lib/libvulkan_freedreno.so" ] || die "libvulkan_freedreno.so não foi gerada"
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
        a8xx-gen8)
            pretty_name="Turnip A8xx Gen8"
            desc="A8xx Gen8 Android/Bionic GPU configuration, 64 KiB shared memory and A840v2 support"
            suffix="A8xx-Gen8"
            ;;
        a8xx-patched)
            pretty_name="Turnip A8xx Patched"
            desc="A8xx Android/Bionic balanced configuration with additional 0001-0005 patches"
            suffix="A8xx-Patched"
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
    log "Gerado: $WORKDIR/$zip_name"
}

main() {
    check_deps
    prepare_workdir
    cd "$WORKDIR/mesa"

    log "Mesa: $(git rev-parse HEAD)"
    log "Variante: $VARIANT"

    verify_mesa_mr_44838
    configure_variant
    if [ "$VARIANT" = "a8xx-gen8" ] || [ "$VARIANT" = "a8xx-patched" ]; then
        apply_a8xx_subgroup_fix
    fi
    apply_common_turnip_patches
    if [ "$VARIANT" = "a8xx-gen8" ] || [ "$VARIANT" = "a8xx-patched" ]; then
        apply_Compatibility_a8xx
        apply_a8xx_game_profiles
    fi
    apply_android_ndk_fixes
    build_android
    package_variant
}

main "$@"
