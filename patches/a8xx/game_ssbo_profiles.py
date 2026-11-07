#!/usr/bin/env python3
"""Apply executable-specific SSBO compatibility settings for A8xx."""
from pathlib import Path
import xml.etree.ElementTree as ET

p = Path("src/freedreno/vulkan/00-turnip-defaults.conf")
s = p.read_text(encoding="utf-8")
games = (
    ("MIO: Memories in Orbit", "^mio[.]exe$"),
    ("UNCHARTED: Legacy of Thieves Collection", "^(u4|tll)(-l)?[.]exe$"),
)
for name, regex in games:
    key = f'application_name_match="{regex}"'
    if key in s:
        start = s.rfind("<application", 0, s.index(key))
        end = s.find("</application>", s.index(key))
        if start < 0 or end < 0 or (
            'name="tu_enable_ssbo_emulation" value="true"' not in s[start:end]
        ):
            raise SystemExit(f"game_ssbo_profiles: existing {name} rule lacks SSBO override")
        print(f"game_ssbo_profiles: {name} already present")
        continue
    if f'name="{name}"' in s:
        raise SystemExit(f"game_ssbo_profiles: {name} exists with a different match")
    anchor = "    </device>"
    if anchor not in s:
        raise SystemExit("game_ssbo_profiles: Mesa driconf device anchor missing")
    entry = (
        f'        <application name="{name}" application_name_match="{regex}">\n'
        '            <option name="tu_enable_ssbo_emulation" value="true" />\n'
        '        </application>\n'
    )
    idx = s.rfind(anchor)
    s = s[:idx] + entry + s[idx:]
    print(f"game_ssbo_profiles: added {name}")
ET.fromstring(s)
assert all(s.count(f'application_name_match="{regex}"') == 1 for _, regex in games)
p.write_text(s, encoding="utf-8")
