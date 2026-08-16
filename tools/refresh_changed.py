"""Detect algorithm-code changes in pilog posts and refresh their algoviz
modules.

Usage:
  python tools/refresh_changed.py            # detect only (NO model calls)
  python tools/refresh_changed.py --run      # regenerate changed via deepseek,
                                             # then re-embed posts + sync
Detection baseline: spec/current/ holds the spec snapshot each module was
last generated from; a module is "changed" when the freshly extracted code
differs from the baseline, or the module file is missing. Deferred specs
(spec/deferred/) are skipped unless --include-deferred.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PILOG_ALGO = Path("C:/desktoppp/pilog/blogs/posts/notes/algo")
PY = sys.executable


def extract() -> int:
    posts = sorted(PILOG_ALGO.glob("algorithm-*.md"))
    for f in (ROOT / "spec" / "pending").glob("*.json"):
        f.unlink()
    p = subprocess.run(
        [PY, str(ROOT / "tools" / "extract_from_blog.py"), *[str(x) for x in posts]],
        capture_output=True, text=True,
    )
    if p.returncode != 0:
        sys.exit("extract failed:\n" + p.stdout + p.stderr)
    return len(list((ROOT / "spec" / "pending").glob("*.json")))


def diff_specs() -> tuple[list[str], list[str]]:
    """Returns (changed, new) module ids vs the spec/current baseline."""
    pending = ROOT / "spec" / "pending"
    current = ROOT / "spec" / "current"
    deferred = {f.stem for f in (ROOT / "spec" / "deferred").glob("*.json")}
    changed, new = [], []
    for f in sorted(pending.glob("*.json")):
        mid = f.stem
        if mid in deferred:
            continue
        mod = ROOT / "modules" / f"{mid}.js"
        base = current / f.name
        if not mod.exists() or not base.exists():
            new.append(mid)
            continue
        old_spec = json.loads(base.read_text(encoding="utf-8"))
        new_spec = json.loads(f.read_text(encoding="utf-8"))
        if old_spec.get("code", "").rstrip() != new_spec.get("code", "").rstrip():
            changed.append(mid)
    return changed, new


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true",
                    help="actually regenerate changed modules (deepseek API calls)")
    ap.add_argument("--include-deferred", action="store_true")
    args = ap.parse_args()

    current = ROOT / "spec" / "current"
    if not current.exists():
        current.mkdir(parents=True)
        n = extract()
        for f in (ROOT / "spec" / "pending").glob("*.json"):
            if (ROOT / "modules" / (f.stem + ".js")).exists():
                shutil.copy2(f, current / f.name)
        print(f"baseline initialized from {n} specs "
              f"({len(list(current.glob('*.json')))} with modules)")
        return

    if args.run:
        # embeds shift line numbers — strip them before extracting
        subprocess.run([PY, str(ROOT / "tools" / "embed_in_blog.py"), "--remove"],
                       capture_output=True, text=True)

    n = extract()
    changed, new = diff_specs()
    if not args.include_deferred:
        pass  # already skipped inside diff_specs
    total = len(changed) + len(new)

    if total == 0:
        print(f"checked {n} specs: no code changes detected")
        if args.run:
            subprocess.run([PY, str(ROOT / "tools" / "embed_in_blog.py")],
                           capture_output=True, text=True)
            subprocess.run([PY, str(ROOT / "tools" / "sync_integrations.py")],
                           capture_output=True, text=True)
            print("re-embedded posts + synced integrations (no-op rebuild)")
        return

    print(f"checked {n} specs: {total} need regeneration")
    for mid in changed:
        print(f"  changed: {mid}")
    for mid in new:
        print(f"  new:     {mid}")
    if not args.run:
        print("\ndetect-only; rerun with --run to regenerate via deepseek")
        return

    ids = ",".join(changed + new)
    p = subprocess.run(
        [PY, str(ROOT / "tools" / "batch_generate.py"), "--only", ids,
         "--concurrency", "3"],
        timeout=3600,
    )
    # refresh baseline for everything that now has a module
    for f in (ROOT / "spec" / "pending").glob("*.json"):
        if (ROOT / "modules" / (f.stem + ".js")).exists():
            shutil.copy2(f, current / f.name)
    subprocess.run([PY, str(ROOT / "tools" / "embed_in_blog.py")],
                   capture_output=True, text=True)
    subprocess.run([PY, str(ROOT / "tools" / "sync_integrations.py")],
                   capture_output=True, text=True)
    print("\ndone: modules regenerated, posts re-embedded, integrations synced")
    print("next: rebuild pilog (python pilog.py build) and run its tests")
    sys.exit(p.returncode)


if __name__ == "__main__":
    main()
