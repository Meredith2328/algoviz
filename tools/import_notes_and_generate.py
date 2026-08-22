# -*- coding: utf-8 -*-
"""One-shot: import algoviz modules from 机试-style notes.

Pipeline: give one or more note markdown files -> import_from_notes extracts
problem specs (C++/Python + problem link) into spec/import/ -> generate.py
builds each module via the LLM + validates -> rebuild modules.json.

Usage:
  python tools/import_notes_and_generate.py <note.md> [more.md ...] \
      [--spec-out spec/import] [--model deepseek-v4-flash]

All subprocesses take an argv LIST (never a shell string) so note paths cannot
be interpreted as shell. `generate.py` reads the DeepSeek key from
~/.deepseek-key. C++ solutions get validated by cpp_truth.py (g++ + run);
LeetCode-style classes without a main() fall back to expectedOutputs.

This is the engine behind the `algoviz-import` skill.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("notes", nargs="+")
    ap.add_argument("--spec-out", default=str(ROOT / "spec" / "import"))
    ap.add_argument("--model", default="deepseek-v4-flash")
    args = ap.parse_args()

    py = sys.executable
    kw = dict(cwd=ROOT, capture_output=True, text=True)

    # 1) extract specs (argv list only, no shell)
    r = subprocess.run(
        [py, str(ROOT / "tools" / "import_from_notes.py"), *args.notes,
         "--out", args.spec_out], shell=False, **kw)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit("extraction failed")

    specs = sorted(Path(args.spec_out).glob("*.json"))
    if not specs:
        sys.exit("no specs extracted (checked headings for 题号/链接)")

    # 2) generate each module
    ok, fail = 0, []
    for spec in specs:
        print(f"\n===== {spec.stem} =====")
        g = subprocess.run(
            [py, str(ROOT / "tools" / "generate.py"), str(spec),
             "--model", args.model, "--out", str(ROOT / "modules")],
            shell=False, **kw)
        sys.stdout.write(g.stdout)
        sys.stderr.write(g.stderr)
        if g.returncode == 0:
            ok += 1
        else:
            fail.append(spec.stem)

    # 3) rebuild the module manifest
    b = subprocess.run(
        [py, str(ROOT / "tools" / "build_modules_json.py")], shell=False, **kw)
    sys.stdout.write(b.stdout)

    print(f"\n生成完成: {ok} 成功, {len(fail)} 失败")
    if fail:
        print("失败: " + ", ".join(fail))
        sys.exit(1)
    print("→ 同步到下游可用: python tools/sync_integrations.py")


if __name__ == "__main__":
    main()
