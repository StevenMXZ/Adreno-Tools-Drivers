# Turnip Android sources

Android/Bionic Vulkan driver build sources for Adreno GPUs.

Each workflow execution resolves one Mesa `main` commit and builds four variants
from the same revision.

| Variant | Configuration |
| --- | --- |
| A7xx | Standard |
| A7xx OneUI | Display compatibility |
| A8xx Gen8 | A8xx GPU configuration and 64 KiB shared memory |
| A8xx Patched | Additional shader, compute and compatibility fixes |

Build settings: Android NDK r29, KGSL, Vulkan freedreno, Android platform and
AdrenoTools-compatible ZIP packaging.

## Features

- Upstream KGSL timestamp polling and sync fixes are verified before building.
- Sample shading interpolation is restricted to shaders that require it.
- A8xx includes Qualcomm gralloc UBWC, IMapper5, heap accounting and GPU ID fixes.
- A8xx includes LRZ, SSBO offset and buffer descriptor corrections.
- A8xx uses `supports_double_threadsize = False` for subgroup correctness.
- The patched A8xx variant includes additional shader and compute fixes.

## Build

Run `Build Turnip Android Variants` from the Actions tab.

For local builds, install the required Android NDK and compiler dependencies,
then run `./build_turnip.sh` with the desired `VARIANT` and optional
`MESA_COMMIT`. Outputs are placed in `turnip_workdir/`.

The workflow checks all four ZIP files before publishing a release.
