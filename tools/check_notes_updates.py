# -*- coding: utf-8 -*-
"""Check whether source notes/blogs have NEWER code than the built modules.

The repo's modules were generated from fenced code blocks in source markdown:
  - 机试-style notes (D:/CoursesNow/10_课程/面向机试-*.md) -> spec/import
  - pilog blog posts (algorithm-4/5/6.md)           -> spec/{current,pending,deferred}

This script re-reads each source file at the recorded line, extracts the code
block that produced a spec, and compares it to the spec's `code` (which is what
the module was built from). If they differ, the source was edited after the
module was built — the module is now stale.

It only REPORTS; it never modifies anything.

Usage:
  python tools/check_notes_updates.py           # check all specs
  python tools/check_notes_updates.py --note "D:/.../xxx.md"  # only 机试 note
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import import_from_notes as ifn  # noqa: E402

DEFAULT_NOTES = [
    "D:/CoursesNow/10_课程/面向机试-中位数问题和堆专题（含C++模板）.md",
    "D:/CoursesNow/10_课程/面向机试-动态规划洛谷阅读.md",
]
ALGO_DIR = Path("C:/desktoppp/pilog/blogs/posts/notes/algo")


def source_entries(src):
    """Yield (post, line) dicts from a possibly-nested source field."""
    if isinstance(src, dict):
        yield src
    elif isinstance(src, list):
        for x in src:
            if isinstance(x, dict):
                yield x
            elif isinstance(x, list):
                for y in x:
                    if isinstance(y, dict):
                        yield y


def locate_block(path: Path, line: int | None, code: str) -> str | None:
    """Return the CURRENT body of the fenced block nearest `line` in `path`.

    Uses a window around the recorded line and picks the first fenced block
    whose body is either empty-irrelevant or the closest candidate. We return
    the block's current text so the caller can diff it against the spec. Tolerates
    small row drift from edits above."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if line is None:
        return None
    best = None
    for idx in range(max(0, line - 6), min(len(lines), line + 8)):
        m = ifn.FENCE_RE.match(lines[idx])
        if not m:
            continue
        fence = m.group(2)
        body = []
        j = idx + 1
        while j < len(lines) and not lines[j].strip().startswith(fence):
            body.append(lines[j])
            j += 1
        cand = "\n".join(body)
        # strongly prefer the block that matches the spec (it's the one we built)
        if cand.strip() == code.strip():
            return cand
        # otherwise keep the first plausible block as a guess
        if best is None and "".join(cand).strip():
            best = cand
    return best


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", action="store_true",
                    help="check only the 机试 notes (spec/import)")
    ap.add_argument("--save-report", default=str(ROOT / "spec" / "update_report.json"))
    args = ap.parse_args()

    specs = []
    for d in ["import", "current", "pending", "deferred"]:
        dirp = ROOT / "spec" / d
        if not dirp.exists():
            continue
        for sp in sorted(dirp.glob("*.json")):
            specs.append(sp)

    changed, new, errors = [], [], []
    count = 0
    for sp in specs:
        try:
            d = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        code = d.get("code", "")
        if not code:
            continue
        src = d.get("source", {})
        # find the first source file that exists
        target = None
        for e in source_entries(src):
            post = e.get("post") or e.get("note")
            line = e.get("line")
            if not post:
                continue
            p = Path(post)
            if not p.exists():
                continue
            # skip 机试 notes when checking only blog specs via --note
            if args.note and "CoursesNow" in str(p):
                continue
            target = (p, line)
            break
        if target is None:
            continue
        p, line = target
        count += 1
        latest = locate_block(p, line, code)
        if latest is None:
            errors.append((d.get("id"), str(p), line))
            continue
        if latest.strip() == code.strip():
            # source block == spec snapshot -> audio unchanged
            continue
        # source block differs from what we built -> the note was updated
        changed.append((d.get("id"), latest, code))
        print(f"[CHANGED] {d.get('id')}")
        for ln in list(difflib.unified_diff(
                code.splitlines(), latest.splitlines(),
                "spec(built)", "note(now)", lineterm=""))[:50]:
            print("   " + ln)
    print(f"\nchecked {count} locatable specs; {len(changed)} changed; "
          f"{len(errors)} could not locate a block")


if __name__ == "__main__":
    main()
