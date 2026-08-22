# -*- coding: utf-8 -*-
"""Repair modules whose expectedOutputs count doesn't match their input count.

A module declares defaultInput plus testInputs[]; expectedOutputs must line up
one-per-input. Several modules shipped with one fewer expected value, so the
validator compared output[0] against expected[1] and reported bogus failures.

This recomputes the real outputs for every input and rewrites expectedOutputs:

  * Python 题解 -> tools/crosscheck.py (runs the solution in a child process)
  * C++ 题解    -> tools/cpp_truth.py  (compiles with g++ and runs it)

When a module's truth cannot be computed (no single public method, non-LeetCode
shape, no main(), ...) it is reported and left untouched — better a known gap
than a guessed value.

Usage:
  python tools/fix_expected_outputs.py            # report only
  python tools/fix_expected_outputs.py --apply    # rewrite the modules
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"
RUNNER = ROOT / "tools" / "validate_runner.js"
RESULT_PREFIX = "ALGOVIZ_RESULT="

# Modules whose ground truth the checkers cannot model, so their computed values
# must NOT be written back:
#   lc141 — `pos` marks where the list loops; the harness only wires a cycle for
#           the first list arg, so the no-cycle case comes back as the list itself
#   lc160 — needs both lists spliced at the intersection per skipA/skipB, which
#           the harness does not build, so every case degenerates to null
#   lc236 — the answer is a tree NODE; the harness serializes the whole subtree
#           while the module correctly reports the node's value
UNTRUSTED_TRUTH = {
    "lc141-环形链表",
    "lc141-环形链表-v2",
    "lc160-相交链表",
    "lc236-二叉树的最近公共祖先",
}


def module_meta(js: Path) -> dict | None:
    """Ask the runner for the module's metadata (input count, language, ...)."""
    node = shutil.which("node") or "node"
    env = dict(os.environ)
    env["NODE_OPTIONS"] = (
        f"--require {str(RUNNER).replace(os.sep, '/')} "
        f"--require {str(js).replace(os.sep, '/')}"
    )
    env["ALGOVIZ_MODULE_ID"] = js.stem
    env["ALGOVIZ_INPUT_INDEX"] = "-1"
    try:
        p = subprocess.run([node, "-e", ""], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60,
                           cwd=str(ROOT), env=env, shell=False)
    except subprocess.TimeoutExpired:
        return None
    for line in (p.stdout or "").splitlines():
        if line.startswith(RESULT_PREFIX):
            try:
                payload = json.loads(line[len(RESULT_PREFIX):])
            except Exception:
                return None
            return payload.get("meta") if payload.get("ok") else None
    return None


def truth_for(js: Path, language: str | None) -> list[str] | None:
    """Real outputs per input, via the checker that fits the module's language."""
    tool = "cpp_truth.py" if language == "cpp" else "crosscheck.py"
    try:
        p = subprocess.run(
            [sys.executable, str(ROOT / "tools" / tool), str(js)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(ROOT), shell=False,
        )
        payload = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception:
        return None
    if not payload.get("ok"):
        return None
    outs = payload.get("outputs") or []
    return [str(o).replace(" ", "") for o in outs]


def rewrite_expected(js: Path, values: list[str]) -> bool:
    """Replace the module's expectedOutputs array in place.

    The array is located by scanning for its matching close bracket rather than
    a `[^\\]]*` regex: the values themselves contain "]" (e.g. "[[1,6],[8,10]]"),
    which would make a lazy/negated pattern cut the array short and corrupt the
    file. Bracket depth is tracked outside of string literals.
    """
    src = js.read_text(encoding="utf-8")
    m = re.search(r"\n(\s*)expectedOutputs:\s*\[", src)
    if not m:
        return False
    open_idx = src.index("[", m.end() - 1)

    depth = 0
    i = open_idx
    in_str = None
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ('"', "'"):
            in_str = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    else:
        return False
    if depth != 0:
        return False

    body = ", ".join(json.dumps(v, ensure_ascii=False) for v in values)
    src = src[:open_idx] + "[" + body + "]" + src[i + 1:]
    js.write_text(src, encoding="utf-8")
    return True


def same_value(a: str, b: str) -> bool:
    """Whitespace- and number-format-insensitive comparison, matching how the
    validator compares outputs (so "2.0" == "2" and "0.0" == "0")."""
    na, nb = str(a).replace(" ", ""), str(b).replace(" ", "")
    if na == nb:
        return True
    try:
        return float(na.strip('"')) == float(nb.strip('"'))
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the fixes")
    ap.add_argument("--also-values", action="store_true",
                    help="also correct expectedOutputs whose count is right but "
                         "whose values disagree with the computed truth")
    args = ap.parse_args()

    mismatched, fixed, skipped = [], [], []
    for js in sorted(MODULES.glob("*.js")):
        meta = module_meta(js)
        if not meta:
            continue
        expected = meta.get("expectedOutputs")
        n_inputs = int(meta.get("inputCount") or 0)
        if not isinstance(expected, list):
            continue

        count_off = len(expected) != n_inputs
        if not count_off and not args.also_values:
            continue

        if js.stem in UNTRUSTED_TRUTH:
            if count_off:
                skipped.append((js.stem, len(expected), n_inputs, -1))
            continue

        truth = truth_for(js, meta.get("language"))
        if not truth or len(truth) != n_inputs:
            if count_off:
                skipped.append((js.stem, len(expected), n_inputs,
                                len(truth) if truth else 0))
            continue

        # values already agree (whitespace / number-format insensitive)?
        if not count_off and len(expected) == len(truth) and \
                all(same_value(e, t) for e, t in zip(expected, truth)):
            continue

        mismatched.append(js.stem)
        if args.apply and not rewrite_expected(js, truth):
            skipped.append((js.stem, len(expected), n_inputs, -2))
            continue
        fixed.append((js.stem, expected, truth))

    verb = "已修复" if args.apply else "可修复"
    print(f"需要修正的模块: {len(mismatched)}")
    print(f"{verb}: {len(fixed)}")
    for stem, old, new in fixed:
        print(f"  {stem}: {old} -> {new}")
    if skipped:
        print(f"跳过（保持原样）: {len(skipped)}")
        for stem, ne, ni, nt in skipped:
            if nt == -1:
                why = "真值不可建模（见 UNTRUSTED_TRUTH）"
            elif nt == -2:
                why = "无法定位 expectedOutputs 数组"
            else:
                why = f"truth={nt} 不足 {ni} 个"
            print(f"  {stem}: expected={ne} inputs={ni} — {why}")
    if not args.apply:
        print("\n（这是预演，加 --apply 才会写入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
