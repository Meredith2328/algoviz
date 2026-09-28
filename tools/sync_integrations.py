"""Sync the algoviz player + modules into the two consumer projects.

  python sync_integrations.py            # sync both
  python sync_integrations.py pilog      # only pilog
  python sync_integrations.py leetgotya  # only leetgotya
  python sync_integrations.py --pilog D:/src/pilog --leetgotya D:/src/leetgotya

Consumer roots: --pilog/--leetgotya, else $ALGOVIZ_PILOG/$ALGOVIZ_LEETGOTYA,
else ../pilog and ../leetgotya next to this repo, else C:/desktoppp/<name>.

- pilog:     copy player + modules -> pilog/generator/static/algoviz/
- leetgotya: copy player + modules -> leetgotya/algoviz/

Also writes algoviz/manifest.json mapping LeetCode problem number -> module
id/title, so leetgotya can look up a module by question id.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from consumer_paths import ENV_VARS, ConsumerNotFound, resolve_consumer

ROOT = Path(__file__).resolve().parent.parent

LC_RE = re.compile(r"^lc(\d+)-")
LGP_RE = re.compile(r"^lgp(\d+)-")


def validate() -> None:
    """同步前跑完整性校验（文件名长度/引用一致/JS 语法），不过则中止。

    历史事故：286 字节文件名导致下游 Actions checkout 失败；
    manifest 引用未入库模块导致线上 404。见 tools/validate_manifest.py。
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_manifest.py"),
         "--skip-sync-check"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        sys.exit("校验未通过，已中止同步（先修复上述 ERROR 再同步）")


def build_manifest() -> dict:
    entries = []
    for f in sorted((ROOT / "modules").glob("*.js")):
        mid = f.stem
        m = LC_RE.match(mid)
        g = LGP_RE.match(mid)
        num = int(m.group(1)) if m else (100000 + int(g.group(1)) if g else None)
        title = ""
        tm = re.search(r'title:\s*"([^"]*)"', f.read_text(encoding="utf-8"), re.S)
        if tm:
            title = tm.group(1)
        entries.append({"id": mid, "num": num, "title": title})
    return {"count": len(entries), "modules": entries}


def sync(target_dir: Path, name: str = "algoviz") -> None:
    dst = target_dir / name
    if dst.exists():
        shutil.rmtree(dst)
    # pilog's site lives at the user page root; an "algoviz" dir there would
    # be shadowed by the algoviz project Pages at /algoviz/ — use a distinct
    # directory name and remove any stale one from the old layout
    stale = target_dir / ("algoviz" if name != "algoviz" else "algoviz-player")
    if stale.exists():
        shutil.rmtree(stale)
    dst.mkdir(parents=True)
    shutil.copy2(ROOT / "player" / "algoviz.js", dst / "algoviz.js")
    shutil.copy2(ROOT / "player" / "algoviz.css", dst / "algoviz.css")
    (dst / "modules").mkdir()
    n = 0
    for f in (ROOT / "modules").glob("*.js"):
        shutil.copy2(f, dst / "modules" / f.name)
        n += 1
    (dst / "manifest.json").write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"synced {n} modules + player -> {dst}")


def main() -> None:
    ap = argparse.ArgumentParser(description="sync algoviz player + modules into consumers")
    ap.add_argument("which", nargs="?", default="all", choices=["all", "pilog", "leetgotya"])
    ap.add_argument("--pilog", help=f"pilog root (or env {ENV_VARS['pilog']})")
    ap.add_argument("--leetgotya", help=f"leetgotya root (or env {ENV_VARS['leetgotya']})")
    args = ap.parse_args()

    targets = [n for n in ("pilog", "leetgotya") if args.which in ("all", n)]
    try:
        roots = {n: resolve_consumer(n, getattr(args, n)) for n in targets}
    except ConsumerNotFound as e:
        sys.exit(str(e))

    validate()
    if "pilog" in roots:
        sync(roots["pilog"] / "generator" / "static", "algoviz-player")
    if "leetgotya" in roots:
        sync(roots["leetgotya"], "algoviz")


if __name__ == "__main__":
    main()
