#!/usr/bin/env python3
"""
Add the IMapper5 stable-C gralloc backend (SP-HAL loaded) to Mesa.

WHY
    Turnip built with -Dandroid-stub=true can never use Mesa's IMapper backends:
    meson.build pins dep_android_ui / dep_android_mapper4 to null_dep without
    probing, so both are gated out and u_gralloc falls through to
    u_gralloc_fallback.c. That fallback has no lock_ycbcr ("video buffers won't
    be supported"), no colour info, and guesses UBWC from a private-handle
    offset. The three other backends all need a legacy hw_get_module HAL, which
    modern Qualcomm does not ship - the only one present is a 52 KB AOSP stub.

    libui reaches the vendor mapper through AIMapper_loadIMapper(), a plain C
    entry point resolvable via android_load_sphal_library() from a normal app
    process. This backend does that directly: no libui, no libhidlbase, no root.

    Device-confirmed on RedMagic 11 Pro / Adreno 840 / Android 16.

Idempotent. Follows MAINTENANCE.md's three states: already-applied / anchor
present / anchor absent (log and exit 0 - never break the build).
"""
import os
import shutil
import sys

SRC_NAME = "u_gralloc_aimapper.c"
GRALLOC_DIR = "src/util/u_gralloc"

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(HERE, "aimapper", SRC_NAME)

failed = False


def edit(path, old, new, what):
    """Three-state in-place edit."""
    global failed
    if not os.path.exists(path):
        print(f"  WARNING: {path} missing - skipping {what}", file=sys.stderr)
        return
    with open(path) as f:
        content = f.read()

    if new in content:
        print(f"  {path}: {what} already applied")
        return
    if old not in content:
        print(f"  WARNING: {path}: anchor absent for {what} "
              f"- upstream refactored? skipping", file=sys.stderr)
        return

    with open(path, "w") as f:
        f.write(content.replace(old, new, 1))
    print(f"  {path}: {what} applied")


# --- 1. drop the backend source in ------------------------------------------
dst = os.path.join(GRALLOC_DIR, SRC_NAME)
if not os.path.isdir(GRALLOC_DIR):
    print(f"  WARNING: {GRALLOC_DIR} missing - u_gralloc restructured upstream?",
          file=sys.stderr)
    print("add_aimapper_gralloc.py: done (nothing to do)")
    sys.exit(0)

if not os.path.exists(SRC_PATH):
    print(f"  FATAL: companion source {SRC_PATH} not found", file=sys.stderr)
    sys.exit(1)

shutil.copyfile(SRC_PATH, dst)
print(f"  {dst}: backend source installed")

# --- 2. meson: compile it ----------------------------------------------------
edit(
    os.path.join(GRALLOC_DIR, "meson.build"),
    "  'u_gralloc_qcom.c',\n)",
    "  'u_gralloc_qcom.c',\n  'u_gralloc_aimapper.c',\n)",
    "meson source list",
)

# --- 3. public enum ----------------------------------------------------------
edit(
    os.path.join(GRALLOC_DIR, "u_gralloc.h"),
    "   U_GRALLOC_TYPE_GRALLOC4,\n   U_GRALLOC_TYPE_CROS,",
    "   U_GRALLOC_TYPE_GRALLOC4,\n"
    "   /* IMapper5 stable-C, loaded as an SP-HAL. Works without libui, so it is\n"
    "    * the only real backend available under android-stub=true. */\n"
    "   U_GRALLOC_TYPE_AIMAPPER,\n"
    "   U_GRALLOC_TYPE_CROS,",
    "u_gralloc_type enum",
)

# --- 4. internal extern ------------------------------------------------------
edit(
    os.path.join(GRALLOC_DIR, "u_gralloc_internal.h"),
    "extern struct u_gralloc *u_gralloc_qcom_create(void);",
    "extern struct u_gralloc *u_gralloc_aimapper_create(void);\n"
    "extern struct u_gralloc *u_gralloc_qcom_create(void);",
    "create() declaration",
)

# --- 5. selection table ------------------------------------------------------
# After the libui-backed GRALLOC4 entry (so a platform build still prefers it),
# before the legacy hw_get_module backends, which on a modern device only ever
# find an empty AOSP stub.
edit(
    os.path.join(GRALLOC_DIR, "u_gralloc.c"),
    "   {.type = U_GRALLOC_TYPE_LIBDRM, .create = u_gralloc_libdrm_create},",
    "   {.type = U_GRALLOC_TYPE_AIMAPPER, .create = u_gralloc_aimapper_create},\n"
    "   {.type = U_GRALLOC_TYPE_LIBDRM, .create = u_gralloc_libdrm_create},",
    "backend selection table",
)

print("add_aimapper_gralloc.py: done")
