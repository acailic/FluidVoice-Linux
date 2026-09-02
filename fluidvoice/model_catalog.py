"""Model catalog + download cache probe (shared by the web UI today and
the native GTK app; neutral home so webui.py can be deleted)."""
from __future__ import annotations

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
