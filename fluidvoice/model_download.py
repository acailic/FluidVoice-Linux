"""Streaming GGUF downloads for the whisper.cpp backend (stdlib only)."""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__, model_catalog, paths  # noqa: F401 - paths re-exported for callers

Progress = Callable[[int, "int | None"], None]
CHUNK_BYTES = 64 * 1024
CONNECT_TIMEOUT_S = 30  # per-read socket timeout: fails stalled transfers


def download_gguf(name: str, progress: Progress | None = None) -> Path:
    """Fetch a GGUF_CATALOG model into models_dir()/whisper.cpp/.
    Returns the final path; no-op when the file already exists."""
    if name not in model_catalog.GGUF_CATALOG:
        raise ValueError(
            f"unknown gguf model '{name}' "
            f"(choose from {sorted(model_catalog.GGUF_CATALOG)})")
    dest = model_catalog.gguf_path(name)
    if dest.exists():
        return dest
    return download_file(model_catalog.GGUF_CATALOG[name]["url"], dest,
                         progress=progress)


def download_file(url: str, dest: Path, progress: Progress | None = None) -> Path:
    """Stream url -> dest via a sibling .part renamed on success.
    Any failure deletes the .part and re-raises; the final file is never
    left half-written."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(
        url, headers={"User-Agent": f"SayItErmano/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT_S) as resp:
            raw = resp.headers.get("Content-Length")
            total = int(raw) if raw and raw.isdigit() else None
            done = 0
            if progress:
                progress(0, total)
            with open(tmp, "wb") as fh:
                while chunk := resp.read(CHUNK_BYTES):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        if total is not None and done != total:
            raise OSError(f"truncated download: {done}/{total} bytes")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest
