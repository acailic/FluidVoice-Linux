"""Configuration: TOML file at ~/.config/fluidvoice/config.toml.

Every key has a default; the file only needs to contain overrides.
"""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_FILLERS = [
    "um", "uh", "er", "ah", "eh", "umm", "uhh", "err", "ahh", "ehh",
    "hmm", "hm", "mm", "mmm", "erm", "urm", "ugh",
]

DEFAULTS: dict[str, Any] = {
    "general": {
        "language": "auto",  # whisper language code or "auto"
        "copy_to_clipboard": False,  # upstream copyTranscriptionToClipboard
    },
    "hotkey": {
        # X11 keysym name. Modifier-only keys (Right_Control, Right_Alt,
        # Right_Shift, Super_R...) work in "toggle" mode only.
        "key": "Right_Control",
        "modifiers": [],  # any of: ctrl, alt, shift, super
        "mode": "toggle",  # toggle | hold (hold needs a non-modifier key)
        "cancel_key": "",  # optional extra keysym that cancels recording
        "rewrite_key": "",  # optional keysym for Rewrite mode (needs [ai])
    },
    "recording": {
        "command": "auto",  # auto | pw-record | parecord
        "device": "",  # optional PipeWire target / PulseAudio device
        "max_seconds": 300,
        "skip_silent": False,  # skip obviously-silent recordings <= 4s
        "first_pcm_timeout": 2.0,  # fail fast if the mic sends no audio (0 = off)
        "sample_rate": 16000,
        # Spoken-send: a trailing phrase strips and presses Enter after typing
        "spoken_send_enabled": False,
        "spoken_send_phrase": "send it",
        "spoken_send_key": "enter",  # enter | shift+enter | ctrl+enter
        # Live transcription preview while recording
        "preview_enabled": True,
        "preview_mode": "notify",  # notify | overlay (X11 window)
        "preview_interval": 1.2,   # seconds between partial passes
        "preview_min_audio": 1.0,  # seconds before the first partial
    },
    "model": {
        "backend": "auto",  # auto | faster-whisper | whisper-torch | whisper.cpp
        "name": "auto",  # auto -> small (CUDA) / base (CPU); or tiny/base/small/medium/large-v3/large-v3-turbo
        "device": "auto",  # auto | cuda | cpu
        "compute": "auto",  # auto | float16 | int8
        "whispercpp_model": "",  # path to ggml/gguf model for the whisper.cpp backend
    },
    "processing": {
        "remove_filler_words": True,
        "filler_words": list(DEFAULT_FILLERS),
        "punctuation_enabled": True,
        "punctuation_prefix": "literal",  # spoken prefix, e.g. "literal comma"
        "dictionary": [],  # [{ triggers = ["miro board"], replacement = "Miro board" }]
        # GAAV: casual/search-field formatting of the final text
        "gaav_enabled": False,
        "gaav_lowercase_first": True,
        "gaav_remove_trailing_period": True,
    },
    "ai": {
        # OpenAI-compatible chat endpoint (OpenAI, Groq, Ollama /v1, LM Studio, llama.cpp server...)
        "enabled": False,
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "api_key": "",  # preferred: leave empty and use api_key_env
        "api_key_env": "FLUIDVOICE_API_KEY",
        "temperature": 0.2,
        "timeout_seconds": 120,
        "max_retries": 3,
    },
    "insertion": {
        "mode": "typed",  # typed | paste | auto (typed, falls back to paste)
        "type_delay_ms": 8,
        "paste_threshold_chars": 1200,  # longer texts use clipboard paste
    },
    "sounds": {
        "enabled": True,
        "volume": 1.0,  # 0.0 - 1.0
    },
    "notifications": {
        "enabled": True,
    },
    "history": {
        "save": True,
        "save_audio": False,
        "audio_budget_gb": 4.0,
    },
    "server": {
        # Local settings web UI (127.0.0.1 only) - like upstream's local API
        "enabled": True,
        "port": 47735,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: Path | None = None) -> dict:
    """Load config, deep-merged over DEFAULTS. Unknown keys are kept."""
    import os
    path = path or Path(os.environ.get("FLUIDVOICE_CONFIG") or "") \
        if os.environ.get("FLUIDVOICE_CONFIG") else (path or paths.config_file())
    user: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            user = tomllib.load(fh)
    return _deep_merge(DEFAULTS, user)


TEMPLATE = """\
# FluidVoiceLinux configuration.
# Delete any line to fall back to the built-in default.

[general]
# Whisper language code ("auto" detects, or "en", "de", ...)
language = "auto"
# Also copy every transcription to the clipboard
copy_to_clipboard = false

[hotkey]
# X11 keysym name of the dictation hotkey. Examples:
#   "Right_Control", "Right_Alt", "F9", "space", "Pause"
# Modifier-only keys (Right_Control / Right_Alt / Right_Shift / Super_R)
# only work with mode = "toggle".
key = "Right_Control"
# Extra modifiers to require, e.g. ["ctrl", "shift"]
modifiers = []
# "toggle": tap to start, tap again to stop & transcribe.
# "hold":   push-to-talk (non-modifier key only).
mode = "toggle"
# Optional extra key that cancels a running recording (keysym name, "" = off)
cancel_key = ""

[recording]
# auto | pw-record | parecord
command = "auto"
# Optional PipeWire node target (pw-record --target) / PulseAudio source.
device = ""
max_seconds = 300
# Skip recordings <= 4s that are pure silence
skip_silent = false
# Stop early when the microphone sends no audio at all (muted/wrong device)
first_pcm_timeout = 2.0

[model]
# auto | faster-whisper | whisper-torch | whisper.cpp
backend = "auto"
# auto -> "small" when CUDA is available, "base" otherwise.
# Or one of: tiny, base, small, medium, large-v3, large-v3-turbo
name = "auto"
device = "auto"   # auto | cuda | cpu
compute = "auto"  # auto | float16 | int8
# ggml/gguf model path for the whisper.cpp backend
whispercpp_model = ""

[processing]
remove_filler_words = true
# Filler words removed before punctuation formatting
filler_words = ["um", "uh", "er", "ah", "eh", "umm", "uhh", "err", "ahh", "ehh", "hmm", "hm", "mm", "mmm", "erm", "urm", "ugh"]
punctuation_enabled = true
# Spoken commands require this prefix word: "literal comma" -> ","
punctuation_prefix = "literal"
# Custom dictionary: [[ { triggers = ["miro board"], replacement = "Miro board" } ]]
dictionary = []

[ai]
# Optional AI polish of the raw transcript (FluidVoice's headline feature).
# Any OpenAI-compatible /v1/chat/completions endpoint works:
#   OpenAI   https://api.openai.com/v1
#   Groq     https://api.groq.com/openai/v1
#   Ollama   http://localhost:11434/v1
#   LM Studio http://localhost:1234/v1
enabled = false
base_url = "http://localhost:11434/v1"
model = ""
api_key = ""             # preferred: leave empty and export the env var below
api_key_env = "FLUIDVOICE_API_KEY"
temperature = 0.2
timeout_seconds = 120
max_retries = 3

[insertion]
# typed: simulate keystrokes (xdotool type)
# paste: clipboard + Ctrl+V (restores your clipboard afterwards)
# auto: typed, falling back to paste for very long texts
mode = "auto"
type_delay_ms = 8
paste_threshold_chars = 1200

[sounds]
enabled = true
volume = 1.0

[notifications]
enabled = true

[history]
save = true
save_audio = false
audio_budget_gb = 4.0

[server]
# Local settings web UI (`fluidvoice settings`), bound to 127.0.0.1 only
enabled = true
port = 47735
"""


def _write_private(path: Path, text: str) -> None:
    """Atomic write with 0600 - the file may contain an API key."""
    import os
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fluidvoice-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def write_template(path: Path | None = None) -> Path:
    path = path or paths.config_file()
    _write_private(path, TEMPLATE)
    return path


# ---------------------------------------------------------------------------
# Saving (used by the settings UI). Only whitelisted keys are written; values
# for keys the UI does not manage (like ai.api_key) are carried over from the
# existing file so a save never loses them.
# ---------------------------------------------------------------------------

_SAVE_WHITELIST: dict[str, list[str]] = {
    "general": ["language", "copy_to_clipboard"],
    "hotkey": ["key", "modifiers", "mode", "cancel_key", "rewrite_key"],
    "recording": ["command", "device", "max_seconds", "skip_silent",
                  "first_pcm_timeout", "spoken_send_enabled", "spoken_send_phrase",
                  "spoken_send_key", "preview_enabled", "preview_mode",
                  "preview_interval", "preview_min_audio"],
    "model": ["backend", "name", "device", "compute", "whispercpp_model"],
    "processing": ["remove_filler_words", "filler_words", "punctuation_enabled",
                   "punctuation_prefix", "dictionary", "gaav_enabled",
                   "gaav_lowercase_first", "gaav_remove_trailing_period"],
    "ai": ["enabled", "base_url", "model", "api_key", "api_key_env", "temperature",
           "timeout_seconds", "max_retries"],
    "insertion": ["mode", "type_delay_ms", "paste_threshold_chars"],
    "sounds": ["enabled", "volume"],
    "notifications": ["enabled"],
    "history": ["save", "save_audio", "audio_budget_gb"],
    "server": ["enabled", "port"],
}


def _toml_value(value: Any) -> str:
    import json
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON escaping is valid TOML
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            parts.append(f"{k} = {_toml_value(v)}")
        return "{ " + ", ".join(parts) + " }"
    raise ValueError(f"cannot serialize {type(value).__name__} to TOML")


def save_config(cfg: dict, path: Path | None = None) -> Path:
    """Persist the whitelisted config keys as TOML, carrying over api_key."""
    path = path or paths.config_file()
    carry: dict = {}
    if path.exists():
        try:
            with open(path, "rb") as fh:
                carry = tomllib.load(fh)
        except tomllib.TOMLDecodeError:
            carry = {}
    lines: list[str] = ["# FluidVoiceLinux configuration (managed by the settings UI)",
                        ""]
    for section, keys in _SAVE_WHITELIST.items():
        values = cfg.get(section, {})
        carried = carry.get(section, {})
        lines.append(f"[{section}]")
        for key in keys:
            value = values.get(key)
            if value in ("", None) and key in carried:
                value = carried[key]  # e.g. keep an existing api_key
            if value not in ("", None):
                lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    _write_private(path, "\n".join(lines).rstrip() + "\n")
    return path
