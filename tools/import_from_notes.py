# -*- coding: utf-8 -*-
"""Extract C++/Python solutions + problem links from 机试-style notes, and
produce algoviz spec JSON ready for tools/generate.py.

A "note" is a markdown file (e.g. D:/CoursesNow/10_课程/面向机试-*.md) whose
headings name a problem and whose ```cpp / ```python fenced blocks hold the
solution. We pair each code block with the nearest preceding heading (which
may be a markdown link) to derive the problem number/title and a jump link.

To keep a teaching snippet / sub-function out of visualizations, mark its
fence with `-noviz` or a `skip` token (e.g. ```cpp-noviz or ```python skip);
such blocks are skipped entirely during extraction.

Usage:
  python import_from_notes.py <note.md> [more.md ...] [--out spec/import]

Per-block we write spec/<id>.json with:
  id, title, language, link (LeetCode/Luogu only, else omitted),
  code (verbatim), plus hints for OJ-style stdin input.

OJ-style (has main + scanf/printf) gets oj_hint/oj_rules so generate.py tells
the LLM that defaultInput is raw stdin and parseInput should return the text.
This only auto-imports problems whose heading carries a link or a Luogu/LC
problem id; otherwise the block is skipped (use --all to force).
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)\s*(.*)$")
LINK_LUOGU_RE = re.compile(r"https://www\.luogu\.com\.cn/problem/(P?\d+)", re.I)
LINK_LC_RE = re.compile(r"https://leetcode\.cn/problems/[^)/\s]+", re.I)
NOOB_RE = re.compile(r"https://noobdream\.com/[\w/]+", re.I)


def is_marked_skip(info: str) -> bool:
    """True if the info string marks this block "don't visualize".

    Use a `-noviz`/`-skip` suffix on the fence lang (e.g. ```cpp-noviz) or a
    bare `noviz`/`skip` token (e.g. ```python skip) in the note to tell the
    importer to skip this code block entirely. Keeps teaching snippets from
    ever becoming modules.
    """
    info = (info or "").strip().lower()
    return "noviz" in info or "skip" in info


def iter_blocks(text: str):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = FENCE_RE.match(lines[i])
        if m:
            info = m.group(3).strip()
            # strip trailing `-noviz`/`-skip`/`noviz`/`skip` markers off the lang
            lang = info.split()[0].lower() if info else ""
            skip = is_marked_skip(info)
            if skip:
                # remove the marker token(s) so the lang stays clean for callers
                lang = info.replace("noviz", "").replace("skip", "").strip().split()[0].lower() if info.strip() else ""
            fence = m.group(2)
            body = []
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(fence):
                body.append(lines[j])
                j += 1
            yield i + 1, lang, body, skip
            i = j
        else:
            i += 1


def looks_like_solution(lang: str, body: list[str]) -> bool:
    lang = lang.lower()
    if lang in ("text", "txt", "plain", "bash", "sh", "shell", "json", "html",
                "css", "js", "javascript", "java", "go", "sql", "yaml", "output"):
        return False
    joined = "\n".join(body)
    return ("class Solution" in joined or "int main" in joined
            or re.search(r"^\s*(int|void|auto|template|struct|class|using|typedef)\b", joined, re.M) is not None
            or re.search(r"^\s*(def|class)\s+\w+", joined, re.M) is not None)


def norm(sep: str, s: str) -> str:
    keep = re.sub(r"[\W_]+", sep, s).strip(sep)
    return unicodedata.normalize("NFKC", keep)


def detect_language(body: list[str]) -> str:
    """Judge the block's language from its code, not the fence label.

    Some notes fence C++ code under ```python; C++ signature tokens win so we
    set language: "cpp" and the right highlighter.
    """
    joined = "\n".join(body)
    has_cpp = bool(re.search(r"#include\s*<|using namespace|std::|priority_queue|printf\(|scanf\(|int\s+main\s*\(", joined))
    has_py = bool(re.search(r"^def |^class Solution|:\s*$|\bimport \w+|\bprint\(", joined, re.M))
    if has_cpp:
        return "cpp"
    if has_py:
        return "python"
    return "python"


def problem_from_heading(lines_before: list[str], limit: int = 60):
    """Return (num, title, url) by scanning backwards for a problem heading.

    Only genuine problem headings are accepted:
      - a markdown-link heading "[295. 标题](url)" / "[P1048 标题](luogu url)",
      - a 洛谷-example heading "例13-2 **数字三角形**（P1216）".
    Prose lines and stray code lines (e.g. "int a = 233;") are skipped so we
    keep climbing to the real heading.
    """
    cand = [l for l in lines_before
            if not l.strip().startswith('<div class="algoviz"')]
    # any markdown link anywhere in the line: "[文字](url)"
    link_re = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
    for ln in reversed(cand[-limit:]):
        s = ln.strip().lstrip("#").strip()
        if not s or set(s) <= {"-", "=", " ", "#", "*"}:
            continue
        # 1) heading carries a markdown link (LeetCode / Luogu / 机试站)
        um = re.search(r"\((https?://[^)\s]+)\)", s)
        if um:
            url = um.group(1)
            # link text = everything before "](url)", minus the leading "["
            head = s.split("](" + url, 1)[0]
            if "[" in head:
                title_text = head[head.index("["):].lstrip("[").strip()
            else:
                title_text = head.strip()
            m_id = re.search(r"^[例\s]*(?:题)?\s*(\d{1,5}|P\d{2,5})[.\s、-]*", title_text)
            pnum = m_id.group(1) if m_id else None
            if not pnum:
                lg = LINK_LUOGU_RE.search(url)
                if lg:
                    pnum = lg.group(1)
            title = clean_title(re.sub(r"^[例\s]*(?:题)?\s*(?:\d{1,5}|P\d{2,5})[.\s、-]*", "", title_text))
            return title, pnum, url
        # 2) Luogu example heading: 例13-x **标题**（Pxxxx）
        if re.match(r"^例\d+-\d+", s):
            m_p = re.search(r"[（(]\s*(P\d{2,5})\s*[）)]", s)
            pnum = m_p.group(1) if m_p else None
            title = clean_title(re.sub(r"^例\d+-\d+\s*\**\s*", "", s))
            return title, pnum, None
        # anything else: prose / code line — keep scanning
    return None, None, None


def clean_title(s: str) -> str:
    s = s.replace("**", "").strip()
    s = s.replace("[]", "").replace("】", "")      # stray empty brackets
    s = re.sub(r"[\[\]【】]", " ", s)              # drop bracket wrappers
    # strip a leading bracket id like "[P1048 [NOIP 2005 普及组] 采药 - 洛谷]"
    s = re.sub(r"^[例\s]*(?:题)?\s*(?:P?\d{2,5})\s*", "", s)
    s = re.sub(r"^NOIP\s*\d{4}\s*[-\s]*", "", s)
    s = s.rstrip("]").strip()
    s = re.sub(r"^[（(]\s*P?\d{2,5}\s*[）)]\s*", "", s)
    s = re.sub(r"[\s]*[（(]\s*P?\d{2,5}\s*[）)]\s*$", "", s)
    s = re.sub(r"\s*[-–—]\s*洛谷\s*$", "", s)
    s = re.sub(r"\b\[?(NOIP|NOI|APIO|IOI|CSP|USACO|普及组|提高组|省选|国赛)\s*\d{0,4}\s*\]?\b", "", s)
    s = re.sub(r"\s*#(ide|code|sample)\s*$", "", s)
    return re.sub(r"[\s{}]+", " ", s).strip()


def build_id(num: str, title: str, url: str | None) -> str:
    if not num:
        return "note-" + norm("-", title)[:30] + "-src"
    the_num = num.upper()
    slug = norm("-", title).lower()[:40] or "prob"
    digits = re.sub(r"\D", "", the_num) or "0"
    # prefix by the problem's source site (P-number -> Luogu, .cn/LC -> lc,
    # anything else, e.g. noobdream 机试, -> oj)
    if the_num.startswith("P"):
        return f"lgp{int(digits)}-{slug}"
    if url and LINK_LUOGU_RE.search(url):
        return f"lgp{int(digits)}-{slug}"
    if url and LINK_LC_RE.search(url):
        return f"lc{digits if digits != '0' else '0'}-{slug}"
    return f"oj{digits}-{slug}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("notes", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "spec" / "import"))
    ap.add_argument("--all", action="store_true", help="import blocks with no problem heading too")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    seen: set[str] = set()
    for note in args.notes:
        text = Path(note).read_text(encoding="utf-8")
        lines = text.splitlines()
        for line_no, lang, body, skip in iter_blocks(text):
            if skip:
                print(f"skip (marked -noviz) L{line_no}: {Path(note).name}")
                continue
            if not looks_like_solution(lang, body):
                continue
            if not "".join(body).strip():
                continue
            title, pnum, url = problem_from_heading(lines[: line_no - 1])
            # Only import real problems: a block with no 题号 heading is a
            # teaching snippet (syntax demos, inline examples), not a solution.
            if not pnum and not args.all:
                continue
            language = detect_language(body)
            short = title or (Path(note).stem)
            cid = build_id(pnum or "", short, url)
            if cid in seen:
                cid += "-v2"
            seen.add(cid)

            code = "\n".join(body)
            is_oj = language == "cpp" and bool(re.search(r"\bint\s+main\s*\(", code))
            spec = {
                "id": cid,
                "title": (f"{pnum} {short}" if pnum else short),
                "language": language,
                "code": code,
                "source": {"note": str(Path(note)), "line": line_no},
            }
            # link: only LC / Luogu get a jump button; strip #ide anchors, keep path
            if url:
                if LINK_LC_RE.search(url):
                    spec["link"] = LINK_LC_RE.search(url).group(0).rstrip("/")
                elif LINK_LUOGU_RE.search(url):
                    spec["link"] = LINK_LUOGU_RE.search(url).group(0).rstrip("/")
                elif re.match(r"https://www\.luogu\.com\.cn/problem/\w+", url, re.I):
                    spec["link"] = re.match(r"https://www\.luogu\.com\.cn/problem/\w+", url, re.I).group(0)
                elif NOOB_RE.search(url):
                    # 其他网站（如 noobdream）不加跳转，仅记录来源
                    spec["raw_url"] = url
            # Luogu P-number without a link in the heading — synthesize the
            # canonical problem URL so the jump button still appears.
            if "link" not in spec and pnum and str(pnum).upper().startswith("P"):
                num = str(pnum)[1:]
                if num.isdigit():
                    spec["link"] = f"https://www.luogu.com.cn/problem/P{num}"
            if is_oj:
                spec["oj_hint"] = "本题为标准输入输出（scanf/printf），defaultInput/testInputs 填原始 stdin 多行文本，parseInput 直接返回文本本身"
                spec["oj_rules"] = "7. 本题是 OJ 型输入：defaultInput/testInputs 用原始 stdin 文本（如 \"3 2\\n...\"），parseInput 原样返回该文本（不要按 name=value 解析）；expectedOutputs 填对应 printf 输出的真实值。"

            out = out_dir / f"{cid}.json"
            out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            made += 1
            print(f"{cid}: {spec['title']} [{language}]" + (f" link={spec.get('link','')}" if spec.get("link") else ""))
    print(f"\n{made} specs -> {out_dir}")


if __name__ == "__main__":
    main()
