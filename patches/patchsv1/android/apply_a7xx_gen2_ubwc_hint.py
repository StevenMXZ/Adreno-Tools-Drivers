#!/usr/bin/env python3
"""
WN-Turnip A7xx_gen2 UI-corruption fix for FD740 / Adreno X1-85.

A7xx_gen2 inherits a7xx_base, which does not set enable_tp_ubwc_flag_hint.
Without this hint, certain Vulkan UI / compositor passes show vertical-line
corruption on FD740 (SD8 Gen 2) and X1-85 silicon. We append it via an inline
GPUProps to that single add_gpus block — A7xx_gen1, A7xx_gen3 and A8xx are
untouched.

Idempotent.
"""
import sys

DEVICES_PY = "src/freedreno/common/freedreno_devices.py"

with open(DEVICES_PY, "r") as f:
    content = f.read()

OLD = (
    '        GPUId(chip_id=0xffff43050c01, name="Adreno X1-85"),\n'
    '    ], A6xxGPUInfo(\n'
    '        CHIP.A7XX,\n'
    '        [a7xx_base, a7xx_gen2],\n'
)
NEW = (
    '        GPUId(chip_id=0xffff43050c01, name="Adreno X1-85"),\n'
    '    ], A6xxGPUInfo(\n'
    '        CHIP.A7XX,\n'
    '        [a7xx_base, a7xx_gen2, GPUProps(enable_tp_ubwc_flag_hint = True)],\n'
)

if NEW in content:
    print(f"  {DEVICES_PY}: A7xx_gen2 UBWC hint already applied to FD740 / X1-85")
elif OLD in content:
    content = content.replace(OLD, NEW, 1)
    try:
        compile(content, DEVICES_PY, "exec")
    except SyntaxError as e:
        print(f"  FATAL: syntax error after patching at line {e.lineno}: {e.msg}", file=sys.stderr)
        sys.exit(1)
    with open(DEVICES_PY, "w") as f:
        f.write(content)
    print(f"  {DEVICES_PY}: applied enable_tp_ubwc_flag_hint to FD740 / X1-85")
else:
    print(f"  WARNING: FD740 / X1-85 anchor not matched, skipping", file=sys.stderr)

print("apply_a7xx_gen2_ubwc_hint.py: done")
