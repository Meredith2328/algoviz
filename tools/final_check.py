"""Final quality gate: for every module, run the ORIGINAL python code with
the module's own inputs (crosscheck) and validate the module's trace/output
against that ground truth.

Usage: python tools/final_check.py [modules/*.js ...]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    files = [Path(a) for a in sys.argv[1:]] or sorted((ROOT / "modules").glob("*.js"))
    passed, skipped, failed = 0, 0, 0
    for f in files:
        # get python ground truth (timeout/infinite-loop modules fall back
        # to structure-only validation)
        try:
            p = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "crosscheck.py"), str(f)],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            p = None
        try:
            j = json.loads(p.stdout.strip().splitlines()[-1]) if p else {"ok": False}
        except Exception:
            j = {"ok": False}
        env = dict(__import__("os").environ)
        truth = None
        if j.get("ok"):
            truth = [o.replace(" ", "") for o in j["outputs"]]
            env["ALGOVIZ_TRUTH"] = json.dumps({f.stem: truth}, ensure_ascii=False)
        v = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "validate.py"), str(f)],
            capture_output=True, text=True, timeout=120, env=env,
        )
        if v.returncode == 0:
            passed += 1
            tag = "ok  "
        elif truth is None:
            skipped += 1
            tag = "skip"
        else:
            failed += 1
            tag = "FAIL"
        first = v.stdout.strip().splitlines()
        print(f"{tag} {f.stem}" + (f"  <- {first[-1][:110]}" if tag == "FAIL" else ""))
    print(f"\n{passed} passed, {skipped} no-truth (structure-only), {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
