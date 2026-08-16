"""Insert algoviz embeds into pilog algo posts, above each solution block
that has a generated module.

Usage:
  python embed_in_blog.py            # insert all missing
  python embed_in_blog.py --remove   # remove all algoviz embed lines

An embed is one raw-HTML line:
  <div class="algoviz" data-module="<id>" data-title="<title> · 步骤可视化"></div>

Skipped automatically when the post already embeds that module id nearby.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILOG_ALGO = Path("C:/desktoppp/pilog/blogs/posts/notes/algo")
EMBED_RE = re.compile(r'^<div class="algoviz" data-module="([^"]+)".*?></div>\s*$')


def load_specs() -> dict[str, dict]:
    specs = {}
    for f in (ROOT / "spec" / "pending").glob("*.json"):
        s = json.loads(f.read_text(encoding="utf-8"))
        specs[s["id"]] = s
    return specs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--post", default="")  # only one file stem, e.g. algorithm-4
    args = ap.parse_args()

    specs = {} if args.remove else load_specs()
    # group by post file
    by_post: dict[Path, list[dict]] = {}
    for s in specs.values():
        post = Path(s["source"]["post"])
        if args.post and post.stem != args.post:
            continue
        by_post.setdefault(post, []).append(s)

    if args.remove:
        for post in sorted(PILOG_ALGO.glob("algorithm-*.md")):
            lines = post.read_text(encoding="utf-8").splitlines()
            kept = [ln for ln in lines if not EMBED_RE.match(ln.strip())]
            if len(kept) != len(lines):
                post.write_text("\n".join(kept) + "\n", encoding="utf-8")
                print(f"removed embeds from {post.name}")
        return

    total = 0
    for post, items in sorted(by_post.items()):
        lines = post.read_text(encoding="utf-8").splitlines()
        existing = {m.group(1) for ln in lines if (m := EMBED_RE.match(ln.strip()))}
        # insert from the bottom up so line numbers stay valid
        items.sort(key=lambda s: s["source"]["line"], reverse=True)
        n = 0
        for s in items:
            if s["id"] in existing:
                continue
            module = ROOT / "modules" / (s["id"] + ".js")
            if not module.exists():
                continue
            i = s["source"]["line"] - 1  # 0-based index of the opening fence
            title = s["title"].replace('"', "")
            embed = (f'<div class="algoviz" data-module="{s["id"]}" '
                     f'data-title="{title} · 步骤可视化"></div>')
            lines.insert(i, embed)
            n += 1
        if n:
            post.write_text("\n".join(lines) + "\n", encoding="utf-8")
            total += n
            print(f"{post.name}: +{n} embeds")
    print(f"total {total} embeds")


if __name__ == "__main__":
    main()
