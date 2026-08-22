# -*- coding: utf-8 -*-
"""Build modules.json for the algoviz site: [{id, title}, ...]

Equivalent to the original tools/build_modules_json.js but in Python so it is
easy to edit. Reads modules/*.js, extracts each module's title, and writes a
sorted [{id, title}] list. Sorting puts LeetCode (lc) first, then Luogu (lgp),
then any other id (oj / note- / custom). Luogu numbers get +100000 so they
never interleave with same-numbered LeetCode problems (e.g. P1048 vs LC1048).

Usage:
  python tools/build_modules_json.py [out.json]   # default modules.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"

TITLE_RE = re.compile(r'title:\s*"((?:[^"\\]|\\.)*)"')
LC_RE = re.compile(r"^lc(\d+)-|^lc(\d+)$")
LGP_RE = re.compile(r"^lgp(\d+)-|^lgp(\d+)$")


def prob_num(pid: str) -> int:
    m = LC_RE.match(pid)
    if m:
        return int(m.group(1) or m.group(2))
    g = LGP_RE.match(pid)
    if g:
        return 100000 + int(g.group(1) or g.group(2))
    return 1 << 30


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "modules.json"
    entries = []
    for f in sorted(MODULES.glob("*.js")):
        if f.name.endswith(".js"):
            src = f.read_text(encoding="utf-8")
            m = TITLE_RE.search(src)
            title = m.group(1) if m else f.stem
            entries.append({"id": f.stem, "title": title})
    entries.sort(key=lambda e: (prob_num(e["id"]), e["id"]))
    out.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    print(f"modules.json: {len(entries)} modules -> {out}")


if __name__ == "__main__":
    main()
