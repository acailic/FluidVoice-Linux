"""Named presets of the AI base prompt (sidecar JSON, not config).

Shape: {"<name>": "<base_prompt text>"} in prompt_profiles.json beside the
config. Loading a profile copies its text into the Settings → AI editor;
what is saved in config.toml stays the single source of truth (there is no
active-profile pointer). Mirrors processing/dict_learn.py's store
discipline: missing/corrupt file degrades to {} with one warning, writes
are atomic and 0600 (prompts may hold private content).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .. import paths

log = logging.getLogger(__name__)

MAX_NAME_LEN = 64
_WARN = "prompt-profiles.json unreadable - starting empty"


def _resolve(path) -> Path:
    return Path(path) if path is not None else paths.prompt_profiles_file()


def _clean_name(name: str) -> str:
    name = str(name).strip()
    if not name or len(name) > MAX_NAME_LEN:
        raise ValueError(
            f"profile name must be 1-{MAX_NAME_LEN} characters (got "
            f"{len(name)} after trim)")
    return name


def load_profiles(path=None) -> dict[str, str]:
    """All profiles; a missing file is {}. Unreadable/malformed content
    degrades to {} with exactly one warning, never raises."""
    p = _resolve(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning(_WARN)
        return {}
    if not isinstance(data, dict):
        log.warning(_WARN)
        return {}
    # keep only str:str entries with a non-empty (trimmed) name
    return {str(k): v for k, v in data.items()
            if isinstance(v, str) and str(k).strip()}


def save_profiles(profiles: dict[str, str], path=None) -> None:
    """Atomic write (tmp + os.replace) with 0600 - config.py discipline."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(profiles, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def save_named(name: str, prompt: str, path=None) -> dict:
    """Upsert one profile; returns the full store after the write."""
    name = _clean_name(name)
    profiles = load_profiles(path)
    profiles[name] = str(prompt)
    save_profiles(profiles, path)
    return profiles


def rename_profile(old: str, new: str, path=None) -> dict:
    """Rename in place (order preserved); ValueError if `old` is missing."""
    old, new = _clean_name(old), _clean_name(new)
    profiles = load_profiles(path)
    if old not in profiles:
        raise ValueError(f"no profile named {old!r}")
    out = {new if k == old else k: v for k, v in profiles.items()}
    save_profiles(out, path)
    return out


def delete_profile(name: str, path=None) -> dict:
    """Delete one profile; ValueError if missing."""
    name = _clean_name(name)
    profiles = load_profiles(path)
    if name not in profiles:
        raise ValueError(f"no profile named {name!r}")
    del profiles[name]
    save_profiles(profiles, path)
    return profiles
