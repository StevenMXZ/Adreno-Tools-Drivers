#!/usr/bin/env python3
"""
Idempotent A840v2 chip_id fixup for freedreno_devices.py.

Retail SM8850 phones (e.g. POCO F9 Pro) report the A840 as chip_id 0x44050A21
(KGSL gpu_model "Adreno840v2"). Mesa main only knows 0x44050A31, so Turnip fails with
"device (chip_id = 44050A21) is unsupported". Register the v2 revision on the same
A840 GPU info.

Safe to run multiple times.
"""
import re
import sys

DEVICES_PY = "src/freedreno/common/freedreno_devices.py"

with open(DEVICES_PY, "r") as f:
    content = f.read()

if re.search(r"chip_id=0x(ffff)?44050a21", content, re.IGNORECASE):
    print("  A840v2 chip_id already present, skipping")
    sys.exit(0)

m = re.search(r'^(\s*)GPUId\(chip_id=0xffff44050a31, name="[^"]*"\),\n', content,
              re.IGNORECASE | re.MULTILINE)
if not m:
    print("  FATAL: A840 entry (0xffff44050A31) not found", file=sys.stderr)
    sys.exit(1)

indent = m.group(1)
extra = (f'{indent}GPUId(chip_id=0xffff44050A21, name="Adreno (TM) 840v2"),\n'
         f'{indent}GPUId(chip_id=0x44050A21, name="Adreno (TM) 840v2"), # KGSL\n')
content = content[:m.end()] + extra + content[m.end():]

try:
    compile(content, DEVICES_PY, "exec")
except SyntaxError as e:
    print(f"  FATAL: syntax error after patching at line {e.lineno}: {e.msg}", file=sys.stderr)
    sys.exit(1)

with open(DEVICES_PY, "w") as f:
    f.write(content)
print(f"  Added A840v2 chip_id 0x44050A21 to {DEVICES_PY}")
