#!/usr/bin/env python3
"""Add missing A8xx KGSL chip identifiers without replacing GPU definitions."""
from pathlib import Path
import re

DEVICES = Path("src/freedreno/common/freedreno_devices.py")
text = DEVICES.read_text()

def put_ids(anchor_ids, wanted, description):
    global text
    found = None
    for candidate in anchor_ids:
        m = re.search(r"^\s*GPUId\(chip_id=" + re.escape(candidate) + r"\b[^\n]*$", text, re.M | re.I)
        if m:
            found = m
            break
    if not found:
        raise SystemExit(f"{DEVICES}: cannot locate {description} group; upstream layout changed")
    start = text.rfind("add_gpus([", 0, found.start())
    stop = text.find("], A6xxGPUInfo(", found.end())
    if start == -1 or stop == -1:
        raise SystemExit(f"{DEVICES}: cannot locate boundaries of {description} group")
    additions = []
    for chip_id, name in wanted:
        if re.search(r"GPUId\(chip_id=" + re.escape(chip_id) + r"\b", text, re.I):
            print(f"{DEVICES}: {chip_id} already present")
        else:
            additions.append(f'        GPUId(chip_id={chip_id}, name="Adreno (TM) {name}"), # KGSL\n')
    if additions:
        text = text[:stop] + "".join(additions) + text[stop:]
        print(f"{DEVICES}: added {description} IDs " + ", ".join(x[0] for x in wanted))

# The 810 and 829 entries are present in both source variants or upstream;
# only add the missing speedbin/KGSL aliases.
put_ids(("0xffff44010000", "0x44010000"),
        (("0x44010000", "810"),), "A810")
put_ids(("0x44030a20", "0x44030a00", "0xffff44030a00"),
        (("0x44030A00", "829"), ("0xffff44030A00", "829")), "A829")

put_ids(("0xffff44050A31", "0x44050A31"),
        (("0x44041430", "845"), ("0x44051431", "850")), "3-slice A840")

compile(text, str(DEVICES), "exec")
DEVICES.write_text(text)
