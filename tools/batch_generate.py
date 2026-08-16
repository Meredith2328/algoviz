"""Batch-generate algoviz modules from spec/pending via DeepSeek.

Usage: python batch_generate.py [--model deepseek-v4-flash] [--only id1,id2]
       [--concurrency 2] [--retries 3]

Skips ids that already exist in modules/. Writes a report to spec/report.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
PENDING = ROOT / "spec" / "pending"
MODULES = ROOT / "modules"


def run_one(spec_file: Path, model: str, retries: int) -> dict:
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    mid = spec["id"]
    out = MODULES / f"{mid}.js"
    if out.exists():
        return {"id": mid, "status": "skip-exists"}
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, str(TOOLS / "generate.py"), str(spec_file),
         "--model", model, "--retries", str(retries)],
        capture_output=True, text=True, timeout=1800,
    )
    ok = p.returncode == 0
    return {
        "id": mid,
        "status": "ok" if ok else "fail",
        "seconds": round(time.time() - t0),
        "tail": (p.stdout + p.stderr).strip().splitlines()[-4:],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--only", default="")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--retries", type=int, default=3)
    args = ap.parse_args()

    specs = sorted(PENDING.glob("*.json"))
    if args.only:
        want = set(args.only.split(","))
        specs = [s for s in specs if s.stem in want]
    print(f"{len(specs)} specs to generate (concurrency={args.concurrency})")

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        for r in ex.map(lambda f: run_one(f, args.model, args.retries), specs):
            results.append(r)
            print(f"[{len(results)}/{len(specs)}] {r['id']}: {r['status']} "
                  f"({r.get('seconds', 0)}s)", flush=True)

    ok = sum(1 for r in results if r["status"] == "ok")
    skip = sum(1 for r in results if r["status"] == "skip-exists")
    fail = sum(1 for r in results if r["status"] == "fail")
    (ROOT / "spec" / "report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"\ndone: {ok} ok, {skip} skipped, {fail} fail -> spec/report.json")
    for r in results:
        if r["status"] == "fail":
            print("FAIL " + r["id"] + ": " + " | ".join(r["tail"]))


if __name__ == "__main__":
    main()
