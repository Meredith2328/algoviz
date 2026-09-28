"""Locate the consumer project roots (leetgotya / pilog) that algoviz syncs into.

Resolution order for each consumer (first existing directory wins):
  1. explicit path (CLI arg)
  2. env var (ALGOVIZ_LEETGOTYA / ALGOVIZ_PILOG)
  3. sibling directory next to this repo (../leetgotya, ../pilog)
  4. legacy fallback C:/desktoppp/<name>

An explicit CLI/env path must exist; a typo should fail loudly rather than
silently fall through to another checkout.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENV_VARS = {"leetgotya": "ALGOVIZ_LEETGOTYA", "pilog": "ALGOVIZ_PILOG"}
LEGACY = {"leetgotya": Path("C:/desktoppp/leetgotya"), "pilog": Path("C:/desktoppp/pilog")}


class ConsumerNotFound(Exception):
    pass


def resolve_consumer(name: str, explicit: str | os.PathLike | None = None) -> Path:
    env = ENV_VARS[name]
    for source, value in (("CLI arg", explicit), (env, os.environ.get(env))):
        if value:
            p = Path(value).expanduser()
            if not p.is_dir():
                raise ConsumerNotFound(f"{name}: {source} 指定的路径不存在: {p}")
            return p.resolve()
    candidates = [ROOT.parent / name, LEGACY[name]]
    for p in candidates:
        if p.is_dir():
            return p.resolve()
    raise ConsumerNotFound(
        f"找不到 {name}（尝试了 {', '.join(str(c) for c in candidates)}）；"
        f"用 --{name} <path> 或环境变量 {env} 指定"
    )
