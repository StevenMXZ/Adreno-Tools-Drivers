#!/usr/bin/env python3
"""
Robust equivalent of whitebelyash/mesa-unified turnip/gen8 commit
dcbb41b2 ("freedreno/common: increase shared mem size").

That commit is 32 identical one-line hunks flipping every
`cs_shared_mem_size = 32 * 1024` to `64 * 1024`. As a context patch it
is extremely fragile: the A8xx device blocks are rewritten by the
a8xx_gen8.patch series first, so the trailing hunks reject. A global
string replace produces the byte-identical intended result regardless
of upstream context drift.

Runs from turnip_workdir/mesa (paths relative to Mesa source root).
Idempotent.
"""
import sys

DEVICES_PY = "src/freedreno/common/freedreno_devices.py"

OLD = "cs_shared_mem_size = 32 * 1024"
NEW = "cs_shared_mem_size = 64 * 1024"

with open(DEVICES_PY) as f:
    src = f.read()

n = src.count(OLD)
if n == 0:
    print(f"a8xx_shared_mem.py: no '{OLD}' occurrences (already applied?) — nothing to do")
    sys.exit(0)

src = src.replace(OLD, NEW)

# Fail loudly rather than silently shipping a broken generator input.
try:
    compile(src, DEVICES_PY, "exec")
except SyntaxError as e:
    print(f"a8xx_shared_mem.py: FATAL syntax error after replace at line {e.lineno}: {e.msg}",
          file=sys.stderr)
    sys.exit(1)

with open(DEVICES_PY, "w") as f:
    f.write(src)

print(f"a8xx_shared_mem.py: cs_shared_mem_size 32*1024 -> 64*1024 x{n}")
