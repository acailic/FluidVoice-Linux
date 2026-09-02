"""XDG paths used by FluidVoiceLinux."""
from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "fluidvoice"


def config_file() -> Path:
    import os
    override = os.environ.get("FLUIDVOICE_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.toml"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or "~/.local/share"
    return Path(base).expanduser() / "fluidvoice"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "fluidvoice"


def models_dir() -> Path:
    return cache_dir() / "models"


def history_file() -> Path:
    return data_dir() / "history.jsonl"


def audio_dir() -> Path:
    return data_dir() / "audio"


def socket_path() -> Path:
    override = os.environ.get("FLUIDVOICE_SOCKET")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "fluidvoice.sock"
