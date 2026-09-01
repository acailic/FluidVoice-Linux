"""Transcription history (JSONL) with optional audio retention + budget."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import paths


def append(entry: dict, audio_src: Path | None = None, keep_audio: bool = False,
           budget_gb: float = 4.0) -> None:
    hpath = paths.history_file()
    hpath.parent.mkdir(parents=True, exist_ok=True)
    if audio_src and keep_audio:
        adir = paths.audio_dir()
        adir.mkdir(parents=True, exist_ok=True)
        dst = adir / f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time())}.wav"
        try:
            shutil.copy2(audio_src, dst)
            entry["audio"] = str(dst)
        except OSError:
            pass
        _enforce_budget(adir, budget_gb)
    with open(hpath, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _enforce_budget(adir: Path, budget_gb: float) -> None:
    files = sorted(adir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    budget = budget_gb * 1024 ** 3
    total = sum(f.stat().st_size for f in files)
    for f in reversed(files):  # oldest first
        if total <= budget:
            break
        total -= f.stat().st_size
        f.unlink(missing_ok=True)


def tail(n: int = 20) -> list[dict]:
    hpath = paths.history_file()
    if not hpath.exists():
        return []
    lines = hpath.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out
