#!/usr/bin/env python3
"""Keep double-threadsize disabled for A8xx subgroup correctness."""
from pathlib import Path

p = Path("src/freedreno/common/freedreno_devices.py")
s = p.read_text(encoding="utf-8")
a = s.find("a8xx_base = GPUProps(")
b = s.find("\na8xx_base_raw_magic_regs", a)
if a < 0 or b < 0:
    raise SystemExit("a8xx_double_threadsize: a8xx_base GPUProps block not found")
block = s[a:b]
true_count = block.count("supports_double_threadsize = True,")
false_count = block.count("supports_double_threadsize = False,")
if true_count == 1 and false_count == 0:
    block = block.replace("supports_double_threadsize = True,",
                          "supports_double_threadsize = False,", 1)
    s = s[:a] + block + s[b:]
    compile(s, str(p), "exec")
    p.write_text(s, encoding="utf-8")
    print("a8xx_double_threadsize: changed a8xx_base True -> False")
elif true_count == 0 and false_count == 1:
    print("a8xx_double_threadsize: Mesa False already present")
else:
    raise SystemExit(
        f"a8xx_double_threadsize: unexpected a8xx_base flags "
        f"(True={true_count}, False={false_count})"
    )
