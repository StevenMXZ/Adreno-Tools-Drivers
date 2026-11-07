#!/usr/bin/env python3
"""
Idempotent fixup for freedreno_dev_info.h and tu_cmd_buffer.cc.

Patch 03/10 in tu8_kgsl_26.patch adds both has_image_processing and
disable_gmem, but has_image_processing is already in current Mesa main.
This causes a duplicate member compile error.

This script:
1. Resets freedreno_dev_info.h via git checkout (so the patch hunk
   duplicate is removed), then re-inserts ONLY disable_gmem.
2. Ensures the no_gmem check exists in tu_cmd_buffer.cc.

Safe to run multiple times (idempotent).
"""

import subprocess
import sys
import re

DEV_INFO_H = "src/freedreno/common/freedreno_dev_info.h"
TU_CMD_CC  = "src/freedreno/vulkan/tu_cmd_buffer.cc"

# ── freedreno_dev_info.h ──────────────────────────────────────────────────────

def fix_dev_info():
    with open(DEV_INFO_H, "r") as f:
        content = f.read()

    if "bool disable_gmem;" in content:
        # Check if has_image_processing is a duplicate (appears more than once)
        count = content.count("has_image_processing")
        if count <= 1:
            print(f"{DEV_INFO_H}: disable_gmem already present, nothing to do.")
            return
        # Reset and re-add cleanly
        print(f"{DEV_INFO_H}: duplicate has_image_processing detected — resetting and re-adding disable_gmem only")
    else:
        print(f"{DEV_INFO_H}: disable_gmem missing — adding it")

    # Reset the file to pristine Mesa state
    result = subprocess.run(["git", "checkout", "--", DEV_INFO_H])
    if result.returncode != 0:
        print(f"ERROR: git checkout {DEV_INFO_H} failed", file=sys.stderr)
        sys.exit(1)

    with open(DEV_INFO_H, "r") as f:
        content = f.read()

    # Insert disable_gmem after has_image_processing (already in Mesa main)
    # or after has_salu_int_narrowing_quirk if has_image_processing is not present
    anchor = None
    if "bool has_image_processing;" in content:
        anchor = "bool has_image_processing;"
    elif "bool has_salu_int_narrowing_quirk;" in content:
        anchor = "bool has_salu_int_narrowing_quirk;"

    if anchor is None:
        print(f"WARNING: could not find anchor in {DEV_INFO_H}, skipping disable_gmem insertion", file=sys.stderr)
        return

    insert_line = "      /* If GMEM needs to be disabled for this GPU */\n      bool disable_gmem;"
    content = content.replace(
        anchor,
        anchor + "\n" + insert_line,
        1
    )

    with open(DEV_INFO_H, "w") as f:
        f.write(content)
    print(f"{DEV_INFO_H}: disable_gmem inserted successfully")

# ── tu_cmd_buffer.cc ──────────────────────────────────────────────────────────

NO_GMEM_BLOCK = """\
   bool no_gmem = cmd->device->physical_device->dev_info.props.disable_gmem;
   if (no_gmem) {
       cmd->state.rp.__REASON_FIELD__ = "Unsupported GPU";
       return true;
    }

"""

NO_GMEM_ANCHOR = "   /* can't fit attachments into gmem */"

REASON_FIELDS = ("force_render_mode_reason", "gmem_disable_reason")

def fix_tu_cmd():
    with open(TU_CMD_CC, "r") as f:
        content = f.read()

    if "dev_info.props.disable_gmem" in content:
        print(f"{TU_CMD_CC}: no_gmem check already present, nothing to do.")
        return

    if NO_GMEM_ANCHOR not in content:
        print(f"WARNING: anchor not found in {TU_CMD_CC}, skipping no_gmem insertion", file=sys.stderr)
        return

    reason_field = next((f for f in REASON_FIELDS if f"cmd->state.rp.{f}" in content), None)
    if reason_field is None:
        print(f"WARNING: no known render-mode reason field in {TU_CMD_CC}, skipping no_gmem insertion", file=sys.stderr)
        return
    print(f"{TU_CMD_CC}: using reason field '{reason_field}'")

    block = NO_GMEM_BLOCK.replace("__REASON_FIELD__", reason_field)
    content = content.replace(NO_GMEM_ANCHOR, block + NO_GMEM_ANCHOR, 1)
    with open(TU_CMD_CC, "w") as f:
        f.write(content)
    print(f"{TU_CMD_CC}: no_gmem check inserted successfully")

# ── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Script is called from turnip_workdir/mesa — paths are relative to that directory
    fix_dev_info()
    fix_tu_cmd()
    print("fix_a8xx_dev_info.py: done")
