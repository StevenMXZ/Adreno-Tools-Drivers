#!/usr/bin/env python3
"""
WN-Turnip A7xx_gen1 quirks for A720 / A725 / A730.

Upstream a7xx_gen1 inherits has_early_preamble=True and has_scalar_predicates=True
from a7xx_base. Both cause visual regressions and compute hangs on shipped
A720/A725/A730 silicon. We override them to False in the a7xx_gen1 props block
only — A7xx_gen2 (A740 / X1-85) and A7xx_gen3 (A750+, the A8xx base) are
unaffected because they do not select a7xx_gen1.

Idempotent.
"""
import re
import sys

DEVICES_PY = "src/freedreno/common/freedreno_devices.py"

with open(DEVICES_PY, "r") as f:
    content = f.read()

KEYS = ("has_early_preamble", "has_scalar_predicates")

# Anchor on the block itself: upstream keeps renaming the quirks inside it. The
# body ends at the first unindented line, so it cannot run into the next block.
match = re.search(r"^a7xx_gen1 = GPUProps\(\n((?:[ \t]+.*\n|\n)*?)^[ \t]*\)", content, re.M)

if not match:
    print(f"  WARNING: a7xx_gen1 anchor not matched, skipping", file=sys.stderr)
else:
    body = match.group(1)
    new_body = body
    for key in KEYS:
        entry = re.compile(rf"^([ \t]*{key}[ \t]*=[ \t]*)\w+", re.M)
        if entry.search(new_body):
            new_body = entry.sub(r"\g<1>False", new_body, count=1)
        else:
            new_body += f"        {key} = False,\n"

    if new_body == body:
        print(f"  {DEVICES_PY}: a7xx_gen1 quirks already applied")
    else:
        content = content[:match.start(1)] + new_body + content[match.end(1):]
        try:
            compile(content, DEVICES_PY, "exec")
        except SyntaxError as e:
            print(f"  FATAL: syntax error after patching at line {e.lineno}: {e.msg}", file=sys.stderr)
            sys.exit(1)
        with open(DEVICES_PY, "w") as f:
            f.write(content)
        print(f"  {DEVICES_PY}: set has_early_preamble=False, has_scalar_predicates=False in a7xx_gen1")

print("apply_a7xx_gen1_quirks.py: done")
