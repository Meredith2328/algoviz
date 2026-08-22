# -*- coding: utf-8 -*-
"""algoviz module validator.

  python tools/validate.py <module.js> [module.js ...]

Checks each module's structure and its execution trace:

  * run()/code/title/views present, view types known
  * every step's `line` inside the module's own code
  * every step has a non-empty msg and a views object
  * steps only use views the module declared
  * step count within MAX_STEPS
  * output compared against ground truth (env ALGOVIZ_TRUTH) when available,
    otherwise the module's own expectedOutputs

Exit 0 = all valid.

Execution model: the module is never executed inside this process. Each input
runs in its own short-lived `node` process which Node itself preloads with
tools/validate_runner.js plus the module (see runner header). That keeps module
code isolated, bounds it with a timeout, and gives one JSON line back.

This replaces the older in-process `vm.runInContext` validator.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tools" / "validate_runner.js"
ALLOWED_DIRS = [ROOT / "modules", ROOT / "examples"]

MAX_STEPS = 100000
RUN_TIMEOUT_S = 30
RESULT_PREFIX = "ALGOVIZ_RESULT="

KNOWN_VIEWS = {
    "vars", "array", "bars", "grid", "stack", "queue",
    "tree", "heap", "graph", "output", "callstack", "text",
}


def truth_table() -> dict:
    """ALGOVIZ_TRUTH='{"<id>": ["out1", ...]}' — real python outputs per input."""
    try:
        return json.loads(os.environ.get("ALGOVIZ_TRUTH") or "{}")
    except Exception:
        return {}


TRUTH = truth_table()


def fail(mid: str, msg: str) -> bool:
    print(f"FAIL {mid}: {msg}")
    return False


def loose_eq(a, b) -> bool:
    """Compare ignoring whitespace; treat numerically equal values as equal
    ("2.0" == 2 == "2"). Mirrors the old JS validator's looseEq."""
    def parse(x):
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("[") or s.startswith("{"):
                try:
                    return json.loads(s)
                except Exception:
                    return x
        return x

    a, b = parse(a), parse(b)
    sa = json.dumps(a, ensure_ascii=False, separators=(",", ":"))
    sb = json.dumps(b, ensure_ascii=False, separators=(",", ":"))
    sa = "".join(sa.split())
    sb = "".join(sb.split())
    if sa == sb:
        return True
    # "answer is the root node": python may serialize a whole tree while the
    # module reports just the root value
    if isinstance(b, list) and b and not isinstance(a, list):
        if str(a) == str(b[0]):
            return True
        try:
            if float(a) == float(b[0]):
                return True
        except Exception:
            pass
    try:
        return float(sa.strip('"')) == float(sb.strip('"'))
    except Exception:
        return False


def vet_module_path(raw: str) -> Path | None:
    """Only an existing .js file inside modules/ or examples/ may be run, and its
    path must be whitespace-free because NODE_OPTIONS is space-separated."""
    p = Path(raw).resolve()
    if p.suffix != ".js" or not p.is_file():
        return None
    if not any(p.is_relative_to(d) for d in ALLOWED_DIRS):
        return None
    if any(ch.isspace() for ch in str(p)) or any(ch.isspace() for ch in str(RUNNER)):
        return None
    return p


def run_in_child(module_path: Path, mid: str, input_index: int) -> dict:
    """Run one module/input in an isolated node process; return the runner's JSON.

    Node performs the preloads itself (runner first, so the window-ish global
    exists before the module registers). We pass a fixed argument vector.
    """
    node = shutil.which("node") or "node"
    runner = str(RUNNER).replace(os.sep, "/")
    target = str(module_path).replace(os.sep, "/")
    env = dict(os.environ)
    env["NODE_OPTIONS"] = f"--require {runner} --require {target}"
    env["ALGOVIZ_MODULE_ID"] = mid
    env["ALGOVIZ_INPUT_INDEX"] = str(input_index)
    try:
        proc = subprocess.run(
            [node, "-e", ""],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=RUN_TIMEOUT_S, cwd=str(ROOT), env=env, shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "run", "error": f"timed out after {RUN_TIMEOUT_S}s"}

    for line in (proc.stdout or "").splitlines():
        if line.startswith(RESULT_PREFIX):
            try:
                return json.loads(line[len(RESULT_PREFIX):])
            except Exception:
                return {"ok": False, "stage": "load", "error": "unparsable runner output"}
    why = (proc.stderr or "").strip().splitlines()
    return {"ok": False, "stage": "load", "error": why[0] if why else "no result from runner"}


def validate(file: str) -> bool:
    mid = Path(file).stem
    module_path = vet_module_path(file)
    if module_path is None:
        return fail(mid, "module must be an existing .js file under modules/ or "
                        "examples/ with no whitespace in its path")

    # 1) metadata pass — structure checks, no trace yet
    head = run_in_child(module_path, mid, -1)
    if not head.get("ok"):
        return fail(mid, head.get("error") or "load error")
    meta = head.get("meta") or {}

    if not meta.get("hasRun"):
        return fail(mid, "run() missing")
    code = meta.get("code")
    if not isinstance(code, str) or not code.strip():
        return fail(mid, "code missing")
    if not isinstance(meta.get("title"), str) or not meta.get("title"):
        return fail(mid, "title missing")
    views = meta.get("views") or {}
    if not views:
        return fail(mid, "views missing")
    for key, spec in views.items():
        vtype = (spec or {}).get("type")
        if vtype not in KNOWN_VIEWS:
            return fail(mid, f'view "{key}" has unknown type "{vtype}"')

    n_lines = len(code.replace("\r\n", "\n").split("\n"))
    declared = set(views)

    # 2) one isolated run per input: default first, then each testInput
    ok = True
    for ti in range(int(meta.get("inputCount") or 1)):
        name = f"{mid}:default" if ti == 0 else f"{mid}:test{ti - 1}"
        r = run_in_child(module_path, mid, ti)
        if not r.get("ok"):
            ok = fail(mid, f"{name} {r.get('stage', 'run')} error: {r.get('error')}")
            continue

        steps = r.get("steps")
        if not isinstance(steps, list) or not steps:
            ok = fail(mid, f"{name}: no steps")
            continue
        if int(r.get("stepCount") or 0) > MAX_STEPS:
            ok = fail(mid, f"{name}: {r.get('stepCount')} steps > cap")
            continue

        bad = False
        for i, s in enumerate(steps):
            line = (s or {}).get("line")
            if not isinstance(line, int) or isinstance(line, bool) or line < 1 or line > n_lines:
                ok = fail(mid, f"{name}: step {i} bad line {line} (code has {n_lines} lines)")
                bad = True
                break
            msg = (s or {}).get("msg")
            if not isinstance(msg, str) or not msg.strip():
                ok = fail(mid, f"{name}: step {i} missing msg")
                bad = True
                break
            if not (s or {}).get("hasViews"):
                ok = fail(mid, f"{name}: step {i} missing views")
                bad = True
                break
            for k in ((s or {}).get("viewKeys") or []):
                if k not in declared:
                    ok = fail(mid, f'{name}: step {i} uses undeclared view "{k}"')
                    bad = True
                    break
            if bad:
                break
        if bad:
            continue

        out = r.get("output") if r.get("outputPresent") else None
        truth_for = TRUTH.get(mid)
        if truth_for is not None:
            exp = truth_for[ti] if ti < len(truth_for) else None
        else:
            expected = meta.get("expectedOutputs")
            exp = expected[ti] if isinstance(expected, list) and ti < len(expected) else None
        if exp is not None and r.get("outputPresent") and not loose_eq(out, exp):
            ok = fail(mid, f"{name}: output {json.dumps(out, ensure_ascii=False)} "
                           f"!= python-truth {json.dumps(exp, ensure_ascii=False)}")
            continue

        tail = f", output={json.dumps(out, ensure_ascii=False)}" if r.get("outputPresent") else ""
        print(f"ok   {mid} {name}: {r.get('stepCount')} steps{tail}")
    return ok


def main() -> int:
    files = sys.argv[1:]
    if not files:
        print("usage: python validate.py <module.js> [...]", file=sys.stderr)
        return 2
    results = [validate(f) for f in files]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
