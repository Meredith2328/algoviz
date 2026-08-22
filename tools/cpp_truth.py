# -*- coding: utf-8 -*-
"""Compile-and-run a C++ algoviz module to get real expected outputs.

algoviz modules can be C++ (language: "cpp"). For standalone OJ-style
solutions (a `main()` reading stdin and printing stdout — Luogu kinds, 机试
type), we can compute ground-truth outputs by actually compiling with g++
and feeding each input text to the binary.

Usage:
  python cpp_truth.py <module.js>          # reads code + defaultInput/testInputs
  python cpp_truth.py <spec.json>          # reads spec code + default_input/test_inputs

The input texts are treated as RAW stdin (not "name = value" pairs) — that is
how OJ-style programs read. For each input we print one JSON line per input,
or {"ok": false, "error": ...} when it cannot compile/run.

NOT for LeetCode-style classes without a main(); those return {"ok": false} and
generate.py falls back to the LLM-written expectedOutputs.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def extract_code_and_inputs(js: str) -> tuple[str, list[str]]:
    """Pull `code` and the raw defaultInput/testInputs texts from a module JS.

    Unlike crosscheck.py, input texts are returned verbatim (not parsed to
    dicts) because OJ-style C++ programs read them as raw stdin.
    """
    # --- code (array-join or single string) ---
    code = ""
    m = re.search(r'code:\s*\[((?:.|\n)*?)\]\s*\.join', js, re.S)
    if m:
        parts = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
        code = "\n".join(
            p.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n").replace("\x00", "\\")
            for p in parts
        )
    else:
        m2 = re.search(r'code:\s*"((?:[^"\\]|\\.)*)"', js, re.S)
        if m2:
            code = m2.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

    texts: list[str] = []
    # double-quoted: defaultInput: "..." / testInputs: ["...", ...]
    for t in re.findall(r'defaultInput\s*:\s*"((?:[^"\\]|\\.)*)"', js):
        texts.append(t.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\"))
    arr = re.search(r'testInputs\s*:\s*\[(.*?)\]', js, re.S)
    if arr:
        for t in re.findall(r'"((?:[^"\\]|\\.)*)"', arr.group(1)):
            texts.append(t.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\"))
    # single-quoted: defaultInput: '...' / testInputs: ['...', ...]
    for t in re.findall(r"defaultInput\s*:\s*'((?:[^'\\]|\\.)*)'", js):
        texts.append(t.replace("\\n", "\n").replace("\\'", "'"))
    arr2 = re.search(r"testInputs\s*:\s*\[(.*?)\]", js, re.S)
    if arr2:
        for t in re.findall(r"'((?:[^'\\]|\\.)*)'", arr2.group(1)):
            texts.append(t.replace("\\n", "\n").replace("\\'", "'"))

    # dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return code, uniq


def has_main(code: str) -> bool:
    return bool(re.search(r"\bint\s+main\s*\(", code))


def main() -> None:
    target = Path(sys.argv[1])
    if target.suffix == ".json":
        spec = json.loads(target.read_text(encoding="utf-8"))
        code = spec.get("code", "")
        texts = [spec.get("default_input", "")]
        for t in spec.get("test_inputs", []):
            texts.append(t)
    else:
        js = target.read_text(encoding="utf-8", errors="replace")
        code, texts = extract_code_and_inputs(js)

    if not code.strip():
        print(json.dumps({"ok": False, "error": "no code found"}, ensure_ascii=False))
        return
    if not has_main(code):
        # LeetCode-style class, no main() — can't run standalone
        print(json.dumps({"ok": False, "error": "no main() (LeetCode-style) — use crosscheck or LLM expectedOutputs"}, ensure_ascii=False))
        return

    import shutil
    gpp = shutil.which("g++") or "g++"

    with tempfile.TemporaryDirectory() as tmpdir:
        outs = []
        try:
            # compile once
            exe = str(Path(tmpdir) / "a")
            src = Path(tmpdir) / "main.cpp"
            src.write_text(code, encoding="utf-8")
            cp = subprocess.run(
                [gpp, "-O2", "-std=c++17", src.name, "-o", exe],
                cwd=tmpdir, capture_output=True, text=True, timeout=120,
            )
            if cp.returncode != 0:
                print(json.dumps({"ok": False, "error": "compile failed: " + (cp.stderr or cp.stdout).strip()[:500]}, ensure_ascii=False))
                return
            for t in texts:
                rp = subprocess.run(
                    [exe], input=t, capture_output=True, text=True, timeout=60,
                )
                if rp.returncode != 0:
                    outs.append("__ERR__" + rp.stderr.strip())
                else:
                    outs.append(rp.stdout.strip())
        except Exception as e:
            print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False))
            return
    print(json.dumps({"ok": True, "outputs": outs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
