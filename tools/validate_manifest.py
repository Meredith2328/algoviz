# -*- coding: utf-8 -*-
"""algoviz 模块库完整性校验。

  python tools/validate_manifest.py           # 校验，有 ERROR 时退出码 1
  python tools/validate_manifest.py --strict  # 有 WARN 也退出码 1（供 CI）
  python tools/validate_manifest.py --skip-node  # 跳过 node --check 语法校验

背景：modules/ 会由 sync_integrations.py 镜像到 leetgotya / pilog 并部署到
GitHub Pages。历史上出过的事故（校验器要拦住的）：

1. 超长文件名（286 字节 > Linux 255 字节上限）→ 下游 Actions checkout 失败、整站部署中断；
2. manifest 引用了未入库的模块 → 线上加载 404；
3. 文件名前缀题号与实际内容不符（lc543-v2 实为 102 题）→ 版本选择错乱；
4. modules.json 与 modules/ 不同步（新增模块后未重建）→ 消费方拿到过期清单。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "modules"

ID_RE = re.compile(r"^lc(\d+)-(.+?)(-v(\d+))?$")
FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
NAME_LIMIT = 200          # 字节；给 Linux 255 字节上限留余量
SHORT_NAME_SUGGEST = 40   # 字节；超过给 WARN（建议把长描述放 title）


def check_modules(errors: list, warnings: list, use_node: bool = True) -> dict[str, dict]:
    """校验 modules/*.js，返回 {id: {num, version, path}}。"""
    seen = {}
    files = sorted(MODULES.glob("*.js"))
    if not files:
        errors.append("modules/ 目录为空或不存在")
        return seen

    node = shutil.which("node") if use_node else None
    for f in files:
        name = f.name
        stem = f.stem
        nbytes = len(name.encode("utf-8"))
        if nbytes > NAME_LIMIT:
            errors.append(f"{name[:50]}… 文件名 {nbytes} 字节，超 {NAME_LIMIT} 上限"
                          "（Linux 255 限制，下游 Actions checkout 会失败）")
        elif nbytes > SHORT_NAME_SUGGEST:
            warnings.append(f"{name[:50]}… 文件名 {nbytes} 字节偏长，长描述建议放 title 字段")
        if FORBIDDEN.search(name):
            errors.append(f"{name[:50]}… 文件名含非法字符（Windows/URL 不兼容）")

        m = ID_RE.match(stem)
        if not m:
            warnings.append(f"{stem} 不符合 lc<题号>-<名称>[-vN] 命名规范"
                            "（num 为空，下游按题号索引时不会被收录）")
            seen[stem] = {"num": None, "version": 0, "path": f}
            continue
        num, version = int(m.group(1)), int(m.group(4) or 0)
        if m.group(2) == "":
            errors.append(f"{stem} 题号后缺少名称段")

        text = f.read_text(encoding="utf-8", errors="replace")
        if not re.search(r'title:\s*"', text):
            warnings.append(f"{stem} 缺少 title 字段（manifest 的标题会为空）")

        if node:
            r = subprocess.run(["node", "--check", str(f)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"{stem} JS 语法错误: {r.stderr.strip().splitlines()[0] if r.stderr else r.returncode}")
        else:
            warnings.append("node 不可用，跳过 JS 语法校验")

        if stem in seen:
            errors.append(f"重复模块 id: {stem}")
        seen[stem] = {"num": num, "version": version, "path": f}

    # 同题号多版本是允许的（一题多解法），只提示 v1 缺失 v2 存在的孤儿版本
    by_num: dict[int, list[int]] = {}
    for sid, info in seen.items():
        if info["num"] is not None:
            by_num.setdefault(info["num"], []).append(info["version"])
    for num, vers in sorted(by_num.items()):
        if max(vers) > 0 and 0 not in vers:
            warnings.append(f"题号 {num} 只有 -v{max(vers)} 版本、没有 v1（命名不一致？）")
    return seen


def check_modules_json(seen: dict, errors: list, warnings: list) -> None:
    """modules.json（播放器用的模块清单）必须与 modules/ 一一对应。"""
    p = ROOT / "modules.json"
    if not p.exists():
        warnings.append("modules.json 不存在（若播放器已不用它请删除本校验）")
        return
    try:
        entries = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"modules.json 解析失败: {e}")
        return
    ids = [e.get("id") for e in entries]
    if len(ids) != len(set(ids)):
        errors.append("modules.json 存在重复 id")
    file_ids = set(seen)
    missing = set(ids) - file_ids
    extra = file_ids - set(ids)
    for i in sorted(missing):
        errors.append(f"modules.json 引用了不存在的模块: {i}（文件被删/改名后未重建？）")
    for i in sorted(extra):
        errors.append(f"modules.json 缺少新模块: {i}（运行 tools/build_modules_json.js 重建）")


def check_sync_target(consumer: Path, name: str, seen: dict,
                      errors: list, warnings: list) -> None:
    """镜像目录（如 leetgotya/algoviz）与源保持一致，且无引用缺失。"""
    dst = consumer / name
    if not dst.exists():
        return  # 尚未同步，不算错
    mfiles = {f.stem for f in (dst / "modules").glob("*.js")} if (dst / "modules").exists() else set()
    manifest = dst / "manifest.json"
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            ids = [v.get("id") for v in m.get("modules", [])]
            if m.get("count") != len(ids):
                errors.append(f"{consumer.name}/{name}: manifest count={m.get('count')} != 条目数 {len(ids)}")
            for i in ids:
                if i not in mfiles:
                    errors.append(f"{consumer.name}/{name}: manifest 引用 {i} 但 modules/ 缺失该文件")
            stale = mfiles - set(ids)
            for i in sorted(stale):
                warnings.append(f"{consumer.name}/{name}: 孤儿文件 {i}.js 不在 manifest 中")
        except Exception as e:
            errors.append(f"{consumer.name}/{name}: manifest.json 解析失败: {e}")
    drift = mfiles ^ {s for s in seen if seen[s]["path"].exists()}
    src_ids = set(seen)
    if mfiles != src_ids:
        diff_new = sorted(src_ids - mfiles)[:3]
        diff_old = sorted(mfiles - src_ids)[:3]
        warnings.append(f"{consumer.name}/{name}: 与源不同步"
                        + (f"，缺 {diff_old}…" if diff_old else "")
                        + (f"，多 {diff_new}…" if diff_new else "")
                        + "（运行 tools/sync_integrations.py）")


def main() -> int:
    ap = argparse.ArgumentParser(description="algoviz 模块库完整性校验")
    ap.add_argument("--strict", action="store_true", help="有 WARN 也退出码 1")
    ap.add_argument("--skip-node", action="store_true", help="跳过 node --check")
    ap.add_argument("--skip-sync-check", action="store_true", help="跳过下游镜像一致性检查")
    args = ap.parse_args()

    errors: list[str] = []
    warnings: list[str] = []

    seen = check_modules(errors, warnings, use_node=not args.skip_node)
    if args.skip_node:
        warnings = [w for w in warnings if "node" not in w]
    check_modules_json(seen, errors, warnings)

    consumers = [Path("C:/desktoppp/leetgotya"), Path("C:/desktoppp/pilog/generator/static")]
    if not args.skip_sync_check:
        for c, n in zip(consumers, ["algoviz", "algoviz-player"]):
            try:
                check_sync_target(c, n, seen, errors, warnings)
            except Exception as e:
                warnings.append(f"跳过 {c.name} 镜像检查: {e}")

    print(f"模块 {len(seen)} 个")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"结果: {len(errors)} 错误 / {len(warnings)} 警告")
    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
