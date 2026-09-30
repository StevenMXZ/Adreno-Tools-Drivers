#!/usr/bin/env python3
"""
Bypass the legacy 'gmsm' gralloc magic check so UBWC buffers are detected on
newer Qualcomm gralloc (A8XX/A840). Idempotent.
"""
import sys

GRALLOC = "src/util/u_gralloc/u_gralloc_fallback.c"

with open(GRALLOC, "r") as f:
    content = f.read()

# Check if the old gmsm block exists
OLD_BLOCK = """   uint32_t gmsm = ('g' << 24) | ('m' << 16) | ('s' << 8) | 'm';
   if (hnd->handle->numInts >= 2 && hnd->handle->data[hnd->handle->numFds] == gmsm) {
      /* This UBWC flag was introduced in a5xx. */
      bool ubwc = hnd->handle->data[hnd->handle->numFds + 1] & 0x08000000;
      out->modifier = ubwc ? DRM_FORMAT_MOD_QCOM_COMPRESSED : DRM_FORMAT_MOD_LINEAR;
   }"""

NEW_BLOCK = """   /* UBWC flag detection - bypass legacy gmsm magic check for A8XX/A840.
    * Newer Qualcomm gralloc no longer writes the 'gmsm' header.
    * Without this fix, UBWC buffers are treated as linear -> horizontal lines.
    */
   /* This UBWC flag was introduced in a5xx. */
   if (hnd->handle->numInts >= 2) {
      bool ubwc = hnd->handle->data[hnd->handle->numFds + 1] & 0x08000000;
      out->modifier = ubwc ? DRM_FORMAT_MOD_QCOM_COMPRESSED : DRM_FORMAT_MOD_LINEAR;
   }"""

if OLD_BLOCK in content:
    content = content.replace(OLD_BLOCK, NEW_BLOCK)
    with open(GRALLOC, "w") as f:
        f.write(content)
    print(f"  {GRALLOC}: gmsm bypass applied successfully")
elif "bypass legacy gmsm" in content or "gmsm" not in content:
    print(f"  {GRALLOC}: gmsm already bypassed")
else:
    print(f"  WARNING: {GRALLOC}: unexpected gmsm state, manual review needed", file=sys.stderr)

print("fix_gralloc_flushall.py: done")
