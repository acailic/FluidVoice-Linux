"""Model catalog + download cache probe (shared by the native GTK app,
CLI, and daemon)."""
from __future__ import annotations

from pathlib import Path

from . import backends, paths

# name -> (display size, languages, note)
MODEL_CATALOG: dict[str, dict[str, str]] = {
    "tiny": {"size": "~75 MB", "langs": "99", "note": "fastest, lowest accuracy"},
    "base": {"size": "~145 MB", "langs": "99", "note": "fast; CPU default"},
    "small": {"size": "~484 MB", "langs": "99", "note": "balanced; GPU default"},
    "medium": {"size": "~1.5 GB", "langs": "99", "note": "accurate, heavier"},
    "large-v3": {"size": "~2.9 GB", "langs": "99", "note": "best accuracy"},
    "large-v3-turbo": {"size": "~1.6 GB", "langs": "99",
                       "note": "near-large quality, faster"},
}


# whisper.cpp ggml models (huggingface.co/ggerganov/whisper.cpp) —
# key = file name as stored under models_dir()/whisper.cpp/
GGUF_CATALOG: dict[str, dict[str, str]] = {
    "ggml-base.bin": {
        "size": "~142 MB", "langs": "99", "note": "fast; CPU-friendly",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"},
    "ggml-base.en.bin": {
        "size": "~142 MB", "langs": "en", "note": "fast; English only",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"},
    "ggml-small.bin": {
        "size": "~466 MB", "langs": "99", "note": "balanced",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"},
    "ggml-small.en.bin": {
        "size": "~466 MB", "langs": "en", "note": "balanced; English only",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin"},
    "ggml-medium.bin": {
        "size": "~1.5 GB", "langs": "99", "note": "accurate, heavier",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"},
    "ggml-medium.en.bin": {
        "size": "~1.5 GB", "langs": "en", "note": "accurate; English only",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin"},
    "ggml-large-v3.bin": {
        "size": "~2.9 GB", "langs": "99", "note": "best accuracy (no .en upstream)",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin"},
}

GGUF_DIR_NAME = "whisper.cpp"


def gguf_dir() -> Path:
    return paths.models_dir() / GGUF_DIR_NAME


def gguf_path(name: str) -> Path:
    return gguf_dir() / name


def gguf_downloaded(name: str) -> bool:
    """True when the catalog model's file exists in the managed cache."""
    return name in GGUF_CATALOG and gguf_path(name).is_file()


def model_downloaded(name: str) -> bool:
    """Best-effort check of the faster-whisper download cache (ignores
    in-progress .incomplete blobs)."""
    repo = backends.FW_MODEL_REPOS.get(backends.ALIASES.get(name, name), "")
    if not repo:
        return False
    for root in (paths.models_dir() / "faster-whisper",
                 paths.cache_dir().parent / "huggingface" / "hub"):
        candidate = root / ("models--" + repo.replace("/", "--"))
        if not candidate.exists():
            continue
        for blob in candidate.rglob("*"):
            if blob.is_file() and ".incomplete" not in blob.name:
                return True
    return False
