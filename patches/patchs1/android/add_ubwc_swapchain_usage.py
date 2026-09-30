#!/usr/bin/env python3
"""
Request UBWC-compressed swapchain buffers on Adreno.

WHERE THE VALUE ACTUALLY COMES FROM
    Android 16's Vulkan loader does NOT use vkGetSwapchainGrallocUsageXANDROID
    in the normal path. frameworks/native/vulkan/libvulkan/swapchain.cpp:1450+
    does this instead:

        VkAndroidHardwareBufferUsageANDROID ahb_usage;
        image_format_properties.pNext = &ahb_usage;
        GetPhysicalDeviceImageFormatProperties2(pdev, &image_format_info,
                                                &image_format_properties);
        ...
        *producer_usage = ahb_usage.androidHardwareBufferUsage;
        return VK_SUCCESS;                    <-- returns BEFORE the
                                                  GetSwapchainGrallocUsageX chain

    That chain (usage/2/3/4) is a legacy fallback for old drivers and is never
    reached here. An earlier version of this patch targeted it and had no
    observable effect, which is exactly why.

    Mesa's shared AHB usage calculation carries no vendor bits at all. WinNative
    asks for COLOR_ATTACHMENT -> GPU_FRAMEBUFFER (0x200); SurfaceFlinger's
    consumer side contributes HW_COMPOSER|HW_TEXTURE (0x900); total 0xb00 -
    exactly what the device captures show. The blob returns the same plus
    0x10000000 and gets UBWC. Without UBWC, RedMagic GameSpace's upscaler and
    frame generator have no compressed source to read and the screen goes green,
    then black.

WHAT UPSTREAM NOW DOES FOR US (mesa, 2026-08-12 .. 2026-08-19)
    This patch used to do three things. Upstream absorbed two of them:

      - 491bb61a "vulkan/android: undo forcing linear for mutable format",
        b1bf53eb "unify AHB usage bits calculation", 24c8a889 "allow optimal
        tiling for unorm and srgb mutation". vk_image_info_to_ahb_usage() now
        forces LINEAR for a MUTABLE_FORMAT image only when a
        VkImageFormatListCreateInfo is present AND lists formats that are not
        srgb/unorm variants of each other - and it carries the same
        "Android 16/17 never forwards the format list to this query, so assume
        optimal tiling when it is absent" workaround this patch used to
        implement with a device property. So the whole
        mutable_format_compression_compatible gate is gone from here.

      - e39a340f "vulkan/android: Force linear for VK_IMAGE_COMPRESSION_DISABLED_EXT".
        A refusal is now expressed by ORing in CPU_WRITE_RARELY, which the CPU
        guard below already rejects. So VK_EXT_image_compression_control is
        honoured without this script looking for the struct at all.

    What is left is the one thing Mesa still has no concept of: a vendor usage
    bit asking gralloc for a compressed allocation.

GATING
    The bit is NOT hardcoded here. vk_android.c is shared by every Mesa Vulkan
    driver, so a Qualcomm constant does not belong in it. The value comes from
    vk_physical_device::ahb_vendor_usage_compressed, which Turnip sets to
    0x10000000 (AIDL BufferUsage VENDOR_MASK, bits 28-31); drivers that leave it
    zero add nothing and are unaffected.

    Skipped whenever any CPU usage bit is set: gralloc cannot give a
    CPU-mappable UBWC buffer, and as noted above this is also what makes an
    explicit VK_IMAGE_COMPRESSION_DISABLED_EXT request come out right.

SCOPING - do NOT move this into vk_image_info_to_ahb_usage()
    That function serves two callers with opposite needs:
      (a) ALLOCATION - what usage should a new swapchain buffer be created with.
          UBWC is wanted here.
      (b) REQUIREMENT - what usage an image needs, used when validating an
          IMPORT of an already-allocated AHardwareBuffer. Demanding UBWC here
          rejects every buffer that does not have it.

    A build that added the bit inside that function produced 448
    "nativeImportAhbToVulkan failed" errors and a black screen: WinNative's
    X-server images are allocated in gpu_image.c with
    CPU_READ_OFTEN|CPU_WRITE_OFTEN (logged as usage=0x332) and are therefore
    linear by necessity. A CPU-bit guard inside the function cannot catch this -
    it only sees Vulkan-derived usage, which never carries CPU bits.

    VkAndroidHardwareBufferUsageANDROID chained on the OUTPUT is what
    distinguishes case (a): it means "tell me what to allocate with". Import
    validation never chains it. So the bit goes at that assignment, and only
    there.

    Note this also leaves vk_ahb_probe_format() - which upstream now calls with
    the computed usage (d3420263) - seeing the un-vendored value. Deliberate:
    that matches the behaviour device-confirmed in August, and the probe is not
    asked to validate a Qualcomm vendor bit it may not understand.

Idempotent. Three states per MAINTENANCE.md.
"""
import os
import sys

VK_ANDROID = "src/vulkan/runtime/vk_android.c"
VK_PHYS_DEV_H = "src/vulkan/runtime/vk_physical_device.h"
TU_DEVICE = "src/freedreno/vulkan/tu_device.cc"

ANCHOR_AHB = """   ahb_usage_props =
      vk_find_struct(props->pNext, ANDROID_HARDWARE_BUFFER_USAGE_ANDROID);
   if (ahb_usage_props)
      ahb_usage_props->androidHardwareBufferUsage = ahb_usage;"""

NEW_AHB = """   ahb_usage_props =
      vk_find_struct(props->pNext, ANDROID_HARDWARE_BUFFER_USAGE_ANDROID);
   if (ahb_usage_props) {
      /* WN-Turnip: reaching here means the caller chained
       * VkAndroidHardwareBufferUsageANDROID on the output, i.e. it is asking
       * what to ALLOCATE with - the Android loader sizing up a swapchain
       * buffer. Import-validation paths never chain it, so they keep the
       * unmodified requirement and can still accept linear buffers.
       *
       * Skipped when CPU access is implied: gralloc cannot hand back a
       * CPU-mappable compressed buffer. That guard also covers an explicit
       * VK_IMAGE_COMPRESSION_DISABLED_EXT, which vk_image_info_to_ahb_usage()
       * expresses by adding CPU_WRITE_RARELY.
       */
      uint64_t wn_ahb_usage = ahb_usage;

      if (!(wn_ahb_usage & (AHARDWAREBUFFER_USAGE_CPU_READ_MASK |
                            AHARDWAREBUFFER_USAGE_CPU_WRITE_MASK)))
         wn_ahb_usage |= pdevice->ahb_vendor_usage_compressed;

      ahb_usage_props->androidHardwareBufferUsage = wn_ahb_usage;
   }"""

ANCHOR_PDEV = """   const struct vk_pipeline_cache_object_ops *const *pipeline_cache_import_ops;
};"""

NEW_PDEV = """   const struct vk_pipeline_cache_object_ops *const *pipeline_cache_import_ops;

   /** Vendor AHardwareBuffer usage bit requesting a compressed allocation
    *
    * Meaningful only to the platform gralloc. Zero if the driver has none, in
    * which case nothing is added to the usage handed to the Android loader.
    */
   uint64_t ahb_vendor_usage_compressed;
};"""

ANCHOR_TU = """   device->vk.supported_sync_types = device->sync_types;"""

NEW_TU = """   device->vk.supported_sync_types = device->sync_types;

   /* Qualcomm gralloc reads this from AIDL BufferUsage's VENDOR_MASK (bits
    * 28-31) as "allocate UBWC-compressed". Confirmed on a840: every buffer
    * carrying it is reported compressed and is sized with a metadata plane.
    */
   device->vk.ahb_vendor_usage_compressed = 0x10000000ull;"""

# Our own marker, so "the field exists" can be told apart from "the field exists
# because we put it there". If upstream ever grows its own vendor-usage concept
# this script is absorbed and must step aside rather than fail the build
# (MAINTENANCE.md rule 3).
OUR_MARKER = "/** Vendor AHardwareBuffer usage bit requesting a compressed allocation"
FIELD_NAME = "ahb_vendor_usage_compressed"

failed = False


def edit(path, old, new, what):
    global failed
    if not os.path.exists(path):
        print(f"  WARNING: {path} missing - skipping {what}", file=sys.stderr)
        failed = True
        return
    with open(path) as f:
        content = f.read()

    if new in content:
        print(f"  {path}: {what} already applied")
        return
    if old not in content:
        print(f"  WARNING: {path}: anchor absent for {what} "
              f"- upstream refactored? skipping", file=sys.stderr)
        failed = True
        return

    with open(path, "w") as f:
        f.write(content.replace(old, new, 1))
    print(f"  {path}: {what} applied")


if os.path.exists(VK_PHYS_DEV_H):
    with open(VK_PHYS_DEV_H) as f:
        pdev_h = f.read()
    if FIELD_NAME in pdev_h and OUR_MARKER not in pdev_h:
        print("  upstream now provides its own vendor AHB usage field "
              "- anchor absent / upstream absorbed, skipping")
        print("add_ubwc_swapchain_usage.py: done")
        sys.exit(0)

edit(VK_ANDROID, ANCHOR_AHB, NEW_AHB, "vendor UBWC bit on the AHB usage answer")
edit(VK_PHYS_DEV_H, ANCHOR_PDEV, NEW_PDEV, "vk_physical_device vendor-usage field")
edit(TU_DEVICE, ANCHOR_TU, NEW_TU, "turnip sets the vendor usage bit")

if failed:
    print("  FATAL: a required anchor was missing - the UBWC swapchain fix would "
          "silently not be in this build", file=sys.stderr)
    sys.exit(1)

print("add_ubwc_swapchain_usage.py: done")
