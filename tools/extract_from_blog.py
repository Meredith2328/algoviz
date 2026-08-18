"""Extract LeetCode solutions from pilog algo posts into algoviz spec files.

Scans ```python / ``` fenced blocks in the given markdown files, pairs each
block with the nearest preceding heading or standalone题号 line, and writes
one spec JSON per block into spec/out/ (default: ../spec/pending/).

Usage:
  python extract_from_blog.py <post.md> [more.md ...] [--out ../spec/pending] [--all]
Default keeps only blocks whose heading mentions a LeetCode 题号 (数字开头);
--all keeps every python block.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)\s*(.*)$")


def iter_blocks(text: str):
    """Yield (line_no, lang, body_lines, fence) for fenced blocks.
    Blocks with no info string get lang="" — callers decide by content."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if m:
            lang = m.group(3).strip().split()[0].lower() if m.group(3).strip() else ""
            fence = m.group(2)
            body = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(fence):
                body.append(lines[j])
                j += 1
            yield i + 1, lang, body
            i = j
        else:
            i += 1


def looks_like_solution(lang: str, body: list[str]) -> bool:
    if lang in ("text", "txt", "plain", "bash", "sh", "shell", "json", "html",
                "css", "js", "javascript", "java", "cpp", "c++", "go", "sql", "yaml", "output"):
        return False
    joined = "\n".join(body)
    return "class Solution" in joined or re.search(r"^\s*def \w+\(", joined, re.M) is not None


PROB_RE = re.compile(r"(\d{1,4})\s*[\.\、\s]\s*([^\n]{2,40})")


def find_problem(lines_before: list[str], limit: int = 40) -> tuple[str, str] | None:
    """Nearest 题号 heading/line above the block: returns (num, title).
    algoviz embed lines are transparent (they sit between heading and code).
    Matches plain headings ("543 二叉树的直径") and markdown-link headings
    ("[102. 二叉树的层序遍历](https://...)")."""
    cand = [l for l in lines_before
            if not l.strip().startswith('<div class="algoviz"')]
    link_re = re.compile(r"^\[(\d{1,4})[.\、\s]+([^\]]+)\]\(")
    for ln in reversed(cand[-limit:]):
        s = ln.strip().lstrip("#").strip()
        if not s or set(s) <= {"-", "=", " ", "#"}:
            continue
        m = re.match(r"^(\d{1,4})[\.\、\s]+(.+)$", s)
        if m:
            return m.group(1), m.group(2).strip()
        m = link_re.match(s)
        if m:
            return m.group(1), m.group(2).strip()
    return None


# ids that were renamed after extraction (e.g. linux filename limits) —
# map the auto-generated slug back to the canonical module id
ID_OVERRIDES = {
    # was truncated manually to fix a 286-byte filename on leetgotya
    "lc3-坐标映射很像pytorch的tensor-函数参数使用的坐标是1-16-为了把它映射到行号和列号-需要先映射到0-15-然后使用整除-和取模-本质是移位和位与-而块号可以由行号和列号映射得到-当然也可以直接用原始坐标求得-见下": "lc3-坐标映射",
}


def slugify(num: str, title: str) -> str:
    import unicodedata
    keep = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title).strip("-").lower()
    keep = unicodedata.normalize("NFKC", keep)
    full = f"lc{num}-{keep}" if keep else f"lc{num}"
    if full in ID_OVERRIDES:
        return ID_OVERRIDES[full]
    return full[:40]  # ~120 bytes worst case, under the 255-byte linux limit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("posts", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "spec" / "pending"))
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    seen_ids: dict[str, int] = {}
    for post in args.posts:
        text = Path(post).read_text(encoding="utf-8")
        lines = text.splitlines()
        post_name = Path(post).stem
        for line_no, lang, body in iter_blocks(text):
            if not looks_like_solution(lang, body):
                continue
            if not body or not "".join(body).strip():
                continue
            prob = find_problem(lines[: line_no - 1])
            if not prob and not args.all:
                continue
            num, title = prob or ("", post_name)
            slug = slugify(num, title) if num else f"{post_name}-L{line_no}"
            n = seen_ids.get(slug, 0)
            seen_ids[slug] = n + 1
            if n:
                slug = f"{slug}-v{n + 1}"
            spec = {
                "id": slug,
                "title": (f"{num} {title}" if num else title),
                "code": "\n".join(body),
                "source": {"post": post, "line": line_no},
            }
            (out_dir / f"{slug}.json").write_text(
                json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            made += 1
            print(f"{slug}: {spec['title']} ({len(body)} lines)")
    print(f"\n{made} specs -> {out_dir}")


if __name__ == "__main__":
    main()
