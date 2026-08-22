# -*- coding: utf-8 -*-
"""Backfill a `link` field onto legacy algoviz modules missing it.

Every old module id is `lc<number>-<name>` (a LeetCode problem). LeetCode's
public problems API maps frontend_question_id -> title_slug, so we can build
each module's canonical URL as https://leetcode.cn/problems/<slug>/.

This writes `link: "https://leetcode.cn/problems/<slug>/",` right after the
`title:` line of each module *.js that (a) is named lc<number>-... and (b) has
no `link:` field yet. It never touches modules that already carry a link, and
never rewrites anything else in the file.

Requires the slug mapping at <repo>/tools/lc_slugs.json (a slim
{question_id: title_slug} dict). Refresh it when new LeetCode problems appear:
  curl -s "https://leetcode.cn/api/problems/all/" -o _lc_src.json
  (or rebuild tools/lc_slugs.json from the API response).
Usage:
  python tools/backfill_lc_links.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
SNAPSHOT = ROOT / "tools" / "lc_slugs.json"

LC_ID_RE = re.compile(r"^lc(\d+)-")


def load_slugs() -> dict[int, str]:
    # the slim {frontend_question_id: title_slug} mapping ships with the repo.
    # If it's stale, regenerate with:  curl -s
    # "https://leetcode.cn/api/problems/all/" | python -c '...'  (see README)
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return {int(k): v for k, v in data.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    slugs = load_slugs()
    done, skipped = 0, 0
    for f in sorted(MODULES.glob("lc*.js")):
        stem = f.stem
        m = LC_ID_RE.match(stem)
        if not m:
            continue
        num = int(m.group(1))
        if num not in slugs:
            print(f"skip {stem}: no slug for {num}")
            continue
        src = f.read_text(encoding="utf-8")
        if "link:" in src:
            skipped += 1
            continue
        link = f'    link: "https://leetcode.cn/problems/{slugs[num]}/",'
        # insert right after the title line
        tm = re.search(r"^(    title: \".*\",)$", src, re.M)
        if not tm:
            skipped += 1
            continue
        new = src[:tm.end(1)] + "\n" + link + src[tm.end(1):]
        if args.dry_run:
            print(f"[dry-run] {stem} -> {slugs[num]}")
        else:
            f.write_text(new, encoding="utf-8")
            print(f"added link to {stem} -> /problems/{slugs[num]}/")
        done += 1
    print(f"\n{len(slugs)} slugs loaded; {done} backfilled, {skipped} already-had/no-title")


if __name__ == "__main__":
    main()
