"""Transcription history (JSONL) with entry cap, audio budget and a tail read
that never loads the whole file."""
from __future__ import annotations

import io
import json
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

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


def read_all() -> list[dict]:
    """Every parseable entry, oldest first (small: file is capped at
    MAX_ENTRIES). tail() reads only the last 128 KB, so anything that must
    see the whole file (search, stats, export, rewrite) comes here."""
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
    for entry in reversed(read_all()):
        if len(out) >= limit:
            break
        hay = f"{entry.get('text', '')} {entry.get('raw', '')} " \
              f"{entry.get('app') or ''}".lower()
        if q in hay:
            out.append(entry)
    return out


def audio_path_for(ts: float) -> Path | None:
    for entry in read_all():
        if abs(entry.get("ts", 0) - ts) < 1e-6:
            p = entry.get("audio")
            if p and Path(p).exists():
                return Path(p)
    return None


def _rewrite(keep, drop_audio: bool) -> int:
    """Keep entries matching `keep`; delete the rest (+ their audio)."""
    hpath = paths.history_file()
    entries = read_all()
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


def update_text(ts: float, text: str) -> bool:
    """Rewrite the text of the entry with this timestamp (inline repair,
    research §4: correction must be one step away). Returns whether a
    matching entry was found; audio retention is untouched."""
    hpath = paths.history_file()
    entries = read_all()
    changed = False
    lines = []
    for entry in entries:
        if not changed and abs(entry.get("ts", 0) - ts) < 1e-6:
            entry["text"] = text
            changed = True
        lines.append(json.dumps(entry, ensure_ascii=False))
    if not changed:
        return False
    tmp = hpath.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(hpath)
    return True


def clear(drop_audio: bool = True) -> int:
    """Remove every entry (and retained audio). Returns the count removed."""
    adir = paths.audio_dir()
    if drop_audio and adir.exists():
        for f in adir.glob("*.wav"):
            f.unlink(missing_ok=True)
    return _rewrite(lambda e: False, drop_audio=False)


# -- today-usage stats ---------------------------------------------------------

def today_stats(entries: list[dict], now: float | None = None) -> dict:
    """Dictations/seconds/words since local midnight over `entries`."""
    now = time.time() if now is None else now
    # isdst=-1 lets mktime pick the right DST offset for local midnight
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    today = [e for e in entries if e.get("ts", 0) >= midnight]
    seconds = sum(float(e.get("duration_s") or 0) for e in today)
    words = sum(len(str(e.get("text") or e.get("raw") or "").split())
                for e in today)
    return {"dictations": len(today), "seconds": float(seconds), "words": words}


def format_today(stats: dict) -> str:
    """`"N dictations, M:SS minutes, K words"` (shared by CLI + GTK)."""
    total = int(stats.get("seconds", 0))  # truncate, never round up
    return (f"{stats.get('dictations', 0)} dictations, "
            f"{total // 60}:{total % 60:02d} minutes, "
            f"{stats.get('words', 0)} words")


# -- ZIP export ----------------------------------------------------------------

def export_zip(path: Path, on_note: Callable[[str], None] | None = None) -> int:
    """Zip history + retained audio. Returns the number of entries exported.

    Every entry lands in `history.jsonl`; audio is included only when it
    resolves inside paths.audio_dir() and exists. Skipped/refused audio is
    reported through `on_note`, never raised; OSError from the zip write
    itself propagates to the caller.
    """
    note = on_note or (lambda m: None)
    entries = read_all()
    adir = paths.audio_dir().resolve()
    seen: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("history.jsonl", "w") as fh, \
                io.TextIOWrapper(fh, encoding="utf-8") as out:
            for entry in entries:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
        for entry in entries:
            audio = entry.get("audio")
            if not audio:
                continue
            p = Path(audio)
            try:
                inside = p.resolve().is_relative_to(adir)
            except OSError:  # unresolvable path: treat as outside
                inside = False
            if not inside:
                note(f"refused audio outside audio dir: {audio}")
                continue
            if not p.is_file():
                note(f"skipped missing audio: {audio}")
                continue
            arcname = f"audio/{p.name}"
            if arcname in seen:
                continue
            seen.add(arcname)
            zf.write(p, arcname=arcname)
    return len(entries)
