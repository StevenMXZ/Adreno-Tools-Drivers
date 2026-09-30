#!/usr/bin/env python3
"""
WN-Turnip A8xx GPU support applicator for freedreno_devices.py.

Adjusts upstream Mesa main so A810, A825 and A829 render correctly without
disturbing A830 / A840 / X2-85 (which already work on stock upstream).

- A810 (upstream-native, chip_id=0xffff44010000):
    1) inject disable_gmem=True into the inline GPUProps (broken GMEM).
    2) add the speedbin chip_id 0x44010000 so KGSL firmwares with speedbin
       data resolve to the same entry.
- A829 (upstream-native, chip_id=0x44030a20):
    1) inject disable_gmem=True into the inline GPUProps (broken GMEM).
    2) add KGSL chip_ids 0x44030A00 and 0xffff44030A00.
- A825 (not in upstream): insert a fresh A8xx entry derived from a8xx_gen1
  with the depth-cache overrides this part needs.

Safe to run multiple times.
"""
import sys

DEVICES_PY = "src/freedreno/common/freedreno_devices.py"

with open(DEVICES_PY, "r") as f:
    content = f.read()

changes = []

# ── A810 ──────────────────────────────────────────────────────────────────────

A810_LOCATE = "GPUId(chip_id=0xffff44010000"

A810_OLD_GPUID = '       GPUId(chip_id=0xffff44010000, name="Adreno (TM) 810"),\n'
A810_NEW_GPUID = (
    '       GPUId(chip_id=0x44010000, name="Adreno (TM) 810"),\n'
    '       GPUId(chip_id=0xffff44010000, name="Adreno (TM) 810"),\n'
)

A810_OLD_PROPS = (
    "[a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen1, GPUProps(\n"
    "            gmem_vpc_attr_buf_size = 16384,\n"
    "            gmem_vpc_pos_buf_size = 12288,\n"
    "            gmem_vpc_bv_pos_buf_size = 20480,\n"
    "            # This is possibly also needed for a830 (and all of a8xx),\n"
    "            # move to a8xx_base if confirmed needed for a830.\n"
    "            has_fs_tex_prefetch = False,\n"
    "        )]"
)
A810_NEW_PROPS = (
    "[a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen1, GPUProps(\n"
    "            gmem_vpc_attr_buf_size = 16384,\n"
    "            gmem_vpc_pos_buf_size = 12288,\n"
    "            gmem_vpc_bv_pos_buf_size = 20480,\n"
    "            # This is possibly also needed for a830 (and all of a8xx),\n"
    "            # move to a8xx_base if confirmed needed for a830.\n"
    "            has_fs_tex_prefetch = False,\n"
    "            disable_gmem = True,\n"
    "        )]"
)

if A810_LOCATE not in content:
    print("  WARNING: upstream A810 entry not found; skipping A810 modifications", file=sys.stderr)
else:
    if "GPUId(chip_id=0x44010000" not in content:
        if A810_OLD_GPUID in content:
            content = content.replace(A810_OLD_GPUID, A810_NEW_GPUID, 1)
            changes.append("added speedbin chip_id 0x44010000 to A810 entry")
        else:
            print("  WARNING: A810 GPUId anchor missed", file=sys.stderr)

    a810_idx = content.find(A810_LOCATE)
    a810_window = content[a810_idx:a810_idx + 1200]
    if "disable_gmem = True," in a810_window:
        print("  A810 disable_gmem already present")
    elif A810_OLD_PROPS in content:
        content = content.replace(A810_OLD_PROPS, A810_NEW_PROPS, 1)
        changes.append("injected disable_gmem=True into A810 GPUProps")
    else:
        print("  WARNING: A810 inline GPUProps anchor missed", file=sys.stderr)

# ── A829 ──────────────────────────────────────────────────────────────────────

A829_LOCATE = "GPUId(chip_id=0x44030a20"

A829_OLD_GPUID = '        GPUId(chip_id=0x44030a20, name="Adreno (TM) 829"), # KGSL\n'
A829_NEW_GPUID = (
    '        GPUId(chip_id=0x44030A00, name="Adreno (TM) 829"), # KGSL\n'
    '        GPUId(chip_id=0xffff44030A00, name="Adreno (TM) 829"), # KGSL fallback\n'
    '        GPUId(chip_id=0x44030a20, name="Adreno (TM) 829"), # KGSL\n'
)

A829_OLD_PROPS = (
    "[a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen2,\n"
    "         GPUProps(\n"
    "            shading_rate_matches_vk = True,  # TODO confirm this\n"
    "            sysmem_vpc_bv_pos_buf_size = 24576,\n"
    "         )]"
)
A829_NEW_PROPS = (
    "[a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen2,\n"
    "         GPUProps(\n"
    "            shading_rate_matches_vk = True,  # TODO confirm this\n"
    "            sysmem_vpc_bv_pos_buf_size = 24576,\n"
    "            disable_gmem = True,\n"
    "         )]"
)

if A829_LOCATE not in content:
    print("  WARNING: upstream A829 entry not found; skipping A829 modifications", file=sys.stderr)
else:
    if "GPUId(chip_id=0x44030A00" not in content:
        if A829_OLD_GPUID in content:
            content = content.replace(A829_OLD_GPUID, A829_NEW_GPUID, 1)
            changes.append("added KGSL chip_ids 0x44030A00 / 0xffff44030A00 to A829 entry")
        else:
            print("  WARNING: A829 GPUId anchor missed", file=sys.stderr)

    a829_idx = content.find(A829_LOCATE)
    a829_window = content[a829_idx:a829_idx + 1200]
    if "disable_gmem = True," in a829_window:
        print("  A829 disable_gmem already present")
    elif A829_OLD_PROPS in content:
        content = content.replace(A829_OLD_PROPS, A829_NEW_PROPS, 1)
        changes.append("injected disable_gmem=True into A829 GPUProps")
    else:
        print("  WARNING: A829 inline GPUProps anchor missed", file=sys.stderr)

# ── A825 ──────────────────────────────────────────────────────────────────────

A825_BLOCK = """\

add_gpus([
        GPUId(chip_id=0x44030000, name="Adreno (TM) 825"),
    ], A6xxGPUInfo(
        CHIP.A8XX,
        [a7xx_base, a7xx_gen3, a8xx_base, a8xx_gen1, GPUProps(
            sysmem_ccu_depth_cache_fraction = CCUColorCacheFraction.THREE_QUARTER.value,
            sysmem_per_ccu_depth_cache_size = 96 * 1024,
        )],
        num_ccu = 4,
        num_slices = 2,
        tile_align_w = 96,
        tile_align_h = 32,
        tile_max_w = 16416,
        tile_max_h = 16384,
        num_vsc_pipes = 32,
        cs_shared_mem_size = 32 * 1024,
        wave_granularity = 2,
        fibers_per_sp = 128 * 2 * 16,
        magic_regs = dict(),
        raw_magic_regs = a8xx_base_raw_magic_regs,
    ))
"""

if 'GPUId(chip_id=0x44030000, name="Adreno (TM) 825")' in content or "name=\"FD825\"" in content:
    print("  A825 entry already present, skipping")
else:
    a810_idx = content.find(A810_LOCATE)
    if a810_idx == -1:
        print("  WARNING: cannot locate A810 anchor for A825 insertion", file=sys.stderr)
    else:
        A810_END_ANCHOR = (
            "        magic_regs = dict(),\n"
            "        raw_magic_regs = a8xx_base_raw_magic_regs,\n"
            "    ))\n"
        )
        idx_close = content.find(A810_END_ANCHOR, a810_idx)
        if idx_close == -1:
            print("  WARNING: cannot locate A810 close-paren for A825 insertion", file=sys.stderr)
        else:
            insert_at = idx_close + len(A810_END_ANCHOR)
            content = content[:insert_at] + A825_BLOCK + content[insert_at:]
            changes.append("inserted A825 entry after A810")

# ── Write result ──────────────────────────────────────────────────────────────

if changes:
    try:
        compile(content, DEVICES_PY, "exec")
    except SyntaxError as e:
        print(f"  FATAL: syntax error after patching at line {e.lineno}: {e.msg}", file=sys.stderr)
        sys.exit(1)
    with open(DEVICES_PY, "w") as f:
        f.write(content)
    print(f"  Applied {len(changes)} change(s) to {DEVICES_PY}:")
    for c in changes:
        print(f"    + {c}")
else:
    print(f"  No changes needed in {DEVICES_PY} (already patched or anchors absent)")

print("apply_a8xx_gpus.py: done")
