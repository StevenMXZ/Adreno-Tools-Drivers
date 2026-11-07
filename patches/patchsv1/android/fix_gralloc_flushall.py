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

GEN8_UNGUARDED = """   /* TODO: Actually find a way to detect a Qualcomm vendor allocated buffer */
   /* This UBWC flag was introduced in a5xx. */
   bool ubwc = hnd->handle->data[hnd->handle->numFds + 1] & 0x08000000;
   out->modifier = ubwc ? DRM_FORMAT_MOD_QCOM_COMPRESSED : DRM_FORMAT_MOD_LINEAR;"""

GEN8_COMMENT = """  /* uint32_t gmsm = ('g' << 24) | ('m' << 16) | ('s' << 8) | 'm';
   if (hnd->handle->numInts >= 2 && hnd->handle->data[hnd->handle->numFds] == gmsm) {

   }
   */"""

if NEW_BLOCK in content:
    print(f"  {GRALLOC}: bounds-checked UBWC detection already applied")
elif OLD_BLOCK in content:
    content = content.replace(OLD_BLOCK, NEW_BLOCK, 1)
    with open(GRALLOC, "w") as f:
        f.write(content)
    print(f"  {GRALLOC}: replaced legacy gmsm guard")
elif GEN8_UNGUARDED in content:
    if content.count(GEN8_UNGUARDED) != 1 or content.count(GEN8_COMMENT) != 1:
        sys.exit(f"FATAL: {GRALLOC}: cannot safely normalize gen8 gralloc workaround")
    content = content.replace(GEN8_COMMENT, "", 1)
    content = content.replace(GEN8_UNGUARDED, NEW_BLOCK, 1)
    with open(GRALLOC, "w") as f:
        f.write(content)
    print(f"  {GRALLOC}: converted gen8 unguarded UBWC read to bounds-checked form")
else:
    sys.exit(f"FATAL: {GRALLOC}: unknown UBWC detection layout (upstream changed?)")

print("fix_gralloc_flushall.py: done")
