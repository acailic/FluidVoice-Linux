"""XDG paths used by SayItErmano (community Linux port of FluidVoice).

The app's own identity is "sayit-ermano"; directories from a pre-rename
install (~/.config/fluidvoice, ~/.local/share/fluidvoice, ~/.cache/fluidvoice)
are taken over once, on first run, so settings, history and downloaded
models survive the rebrand.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP_DIR_NAME = "sayit-ermano"
_LEGACY_DIR_NAME = "fluidvoice"


def _migrate_legacy(old: Path, new: Path) -> None:
    """Move the pre-rename fluidvoice/ dir onto the new name (once)."""
    if old.is_dir() and not new.exists():
        try:
            shutil.move(str(old), str(new))
        except OSError:
            pass  # stay on fresh dirs rather than crash mid-startup


def _app_dir(base_env: str, base_fallback: str) -> Path:
    base = Path(os.environ.get(base_env) or base_fallback).expanduser()
    d = base / APP_DIR_NAME
    _migrate_legacy(base / _LEGACY_DIR_NAME, d)
    return d


def config_dir() -> Path:
    return _app_dir("XDG_CONFIG_HOME", "~/.config")


def config_file() -> Path:
    override = os.environ.get("SAYITERMANO_CONFIG")
    if override:
        return Path(override)
    return config_dir() / "config.toml"


def data_dir() -> Path:
    return _app_dir("XDG_DATA_HOME", "~/.local/share")


def cache_dir() -> Path:
    return _app_dir("XDG_CACHE_HOME", "~/.cache")


def models_dir() -> Path:
    return cache_dir() / "models"


def history_file() -> Path:
    return data_dir() / "history.jsonl"


def dictionary_suggestions_file() -> Path:
    """Dictionary auto-learning decisions (dismissed/accepted pairs)."""
    return config_dir() / "dictionary-suggestions.json"


def prompt_profiles_file() -> Path:
    """Named presets of the AI base prompt ({name: prompt})."""
    return config_dir() / "prompt-profiles.json"


def audio_dir() -> Path:
    return data_dir() / "audio"


def socket_path() -> Path:
    override = os.environ.get("SAYITERMANO_SOCKET")
    if override:
        return Path(override)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "sayit-ermano.sock"
