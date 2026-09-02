"""Transcription history (JSONL) with entry cap, audio budget and a tail read
that never loads the whole file."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import paths

MAX_ENTRIES = 5000
_TAIL_WINDOW = 128 * 1024  # bytes read from the end for tail()


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
    _enforce_entry_cap(hpath)


def _enforce_entry_cap(hpath: Path) -> None:
    try:
        if hpath.stat().st_size < _TAIL_WINDOW:
            return
        lines = hpath.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_ENTRIES:
            tmp = hpath.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(lines[-MAX_ENTRIES:]) + "\n", encoding="utf-8")
            tmp.replace(hpath)
    except OSError:
        pass


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
    """Last `n` entries, reading only the final 128 KB of the file."""
    hpath = paths.history_file()
    try:
        size = hpath.stat().st_size
    except OSError:
        return []
    with open(hpath, "rb") as fh:
        fh.seek(max(0, size - _TAIL_WINDOW))
        chunk = fh.read()
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if size > _TAIL_WINDOW and lines:
        lines = lines[1:]  # first line is likely partial
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def _read_all() -> list[dict]:
    try:
        lines = paths.history_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def search(query: str = "", limit: int = 100) -> list[dict]:
    """Entries filtered by a substring over text/raw/app, newest first."""
    q = (query or "").strip().lower()
    if not q:
        return tail(limit)
    out = []
    for entry in reversed(_read_all()):
        if len(out) >= limit:
            break
        hay = f"{entry.get('text', '')} {entry.get('raw', '')} " \
              f"{entry.get('app') or ''}".lower()
        if q in hay:
            out.append(entry)
    return out


def audio_path_for(ts: float) -> Path | None:
    for entry in _read_all():
        if abs(entry.get("ts", 0) - ts) < 1e-6:
            p = entry.get("audio")
            if p and Path(p).exists():
                return Path(p)
    return None


def _rewrite(keep, drop_audio: bool) -> int:
    """Keep entries matching `keep`; delete the rest (+ their audio)."""
    hpath = paths.history_file()
    entries = _read_all()
    kept_lines = []
    removed_audio: list[Path] = []
    removed = 0
    for entry in entries:
        if keep(entry):
            kept_lines.append(json.dumps(entry, ensure_ascii=False))
        else:
            removed += 1
            if drop_audio and entry.get("audio"):
                removed_audio.append(Path(entry["audio"]))
    tmp = hpath.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""),
                   encoding="utf-8")
    tmp.replace(hpath)
    for p in removed_audio:
        p.unlink(missing_ok=True)
    return removed


def delete(ts: float, drop_audio: bool = True) -> int:
    """Remove the entry with this timestamp (and its audio)."""
    return _rewrite(lambda e: abs(e.get("ts", 0) - ts) > 1e-6, drop_audio)


def clear(drop_audio: bool = True) -> int:
    """Remove every entry (and retained audio). Returns the count removed."""
    adir = paths.audio_dir()
    if drop_audio and adir.exists():
        for f in adir.glob("*.wav"):
            f.unlink(missing_ok=True)
    return _rewrite(lambda e: False, drop_audio=False)
