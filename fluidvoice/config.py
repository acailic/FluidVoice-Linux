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
        "tray_enabled": True,  # panel/tray icon while the daemon runs
    },
    "hotkey": {
        # X11 keysym name. Modifier-only keys (Right_Control, Right_Alt,
        # Right_Shift, Super_R...) work in "toggle" mode only.
        "key": "Right_Control",
        "modifiers": [],  # any of: ctrl, alt, shift, super
        "mode": "toggle",  # toggle | hold (hold needs a non-modifier key)
        # macOS parity: Escape cancels an in-progress dictation (discards,
        # nothing typed). Grabbed ONLY while recording; "none" disables.
        "cancel_key": "Escape",
        "rewrite_key": "",  # optional keysym for Rewrite mode (needs [ai])
        "command_key": "",  # optional keysym for Command mode (needs [ai])
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
        "preview_mode": "auto",   # auto (pill, falls back) | overlay | notify
        "preview_interval": 1.2,   # seconds between partial passes
        "preview_min_audio": 1.0,  # seconds before the first partial
        "preview_bottom_offset": 64,  # pill px above the screen bottom edge
        "preview_overlay_size": "medium",  # pill | small | medium | large (macOS sizes)
        "pause_media": True,  # pause MPRIS players while dictating (resume after)
    },
    "model": {
        "backend": "auto",  # auto | faster-whisper | whisper-torch | whisper.cpp
        "name": "auto",  # auto -> small (CUDA) / base (CPU); or tiny/base/small/medium/large-v3/large-v3-turbo
        "device": "auto",  # auto | cuda | cpu
        "compute": "auto",  # auto | float16 | int8
        "whispercpp_model": "",  # path to ggml/gguf model for the whisper.cpp backend
        "eager_warmup": True,  # load the model at daemon start (preview-ready)
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
        # upstream per-app prompt sets: [{"apps": ["zed"], "instructions": "..."}]
        "per_app_prompts": [],
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
    "command": {
        "max_turns": 4,           # agent loop bound (upstream: 20)
        "working_dir": "",       # "" -> $HOME
        "timeout_seconds": 60.0,  # per-command subprocess timeout
        "confirm_timeout_s": 120.0,  # auto-cancel a pending confirmation
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
    path = path or paths.config_file()
    user: dict = {}
    if path.exists():
        with open(path, "rb") as fh:
            user = tomllib.load(fh)
    user.pop("server", None)  # retired web UI section (spec: strip silently)
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
    "general": ["language", "copy_to_clipboard", "tray_enabled"],
    "hotkey": ["key", "modifiers", "mode", "cancel_key", "rewrite_key",
                "command_key"],
    "recording": ["command", "device", "max_seconds", "skip_silent",
                  "first_pcm_timeout", "spoken_send_enabled", "spoken_send_phrase",
                  "spoken_send_key", "preview_enabled", "preview_mode",
                  "preview_interval", "preview_min_audio",
                  "preview_bottom_offset", "preview_overlay_size",
                  "pause_media"],
    "model": ["backend", "name", "device", "compute", "whispercpp_model",
              "eager_warmup"],
    "processing": ["remove_filler_words", "filler_words", "punctuation_enabled",
                   "punctuation_prefix", "dictionary", "gaav_enabled",
                   "gaav_lowercase_first", "gaav_remove_trailing_period"],
    "ai": ["enabled", "base_url", "model", "api_key", "api_key_env", "temperature",
           "timeout_seconds", "max_retries", "per_app_prompts"],
    "insertion": ["mode", "type_delay_ms", "paste_threshold_chars"],
    "sounds": ["enabled", "volume"],
    "notifications": ["enabled"],
    "history": ["save", "save_audio", "audio_budget_gb"],
    "command": ["max_turns", "working_dir", "timeout_seconds",
                "confirm_timeout_s"],
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


# ---------------------------------------------------------------------------
# Settings validation - single source of truth for the web UI, the socket
# API and the native GTK app (moved from webui.py per the native-app spec).
# ---------------------------------------------------------------------------

# (section, key) -> ("float"|"int", (lo, hi)) | ("str", max_len)
SETTING_RANGES: dict[tuple[str, str], Any] = {
    ("recording", "first_pcm_timeout"): ("float", (0.0, 60.0)),
    ("recording", "preview_interval"): ("float", (0.3, 10.0)),
    ("recording", "preview_min_audio"): ("float", (0.3, 10.0)),
    ("recording", "preview_bottom_offset"): ("int", (0, 400)),
    ("hotkey", "key"): ("str", 64),
    ("hotkey", "cancel_key"): ("str", 64),
    ("hotkey", "rewrite_key"): ("str", 64),
    ("hotkey", "command_key"): ("str", 64),
    ("command", "max_turns"): ("int", (1, 20)),
    ("command", "working_dir"): ("str", 4096),
    ("command", "timeout_seconds"): ("float", (1, 3600)),
    ("command", "confirm_timeout_s"): ("float", (5, 600)),
    ("recording", "device"): ("str", 256),
    ("recording", "max_seconds"): ("float", (1, 86400)),
    ("recording", "spoken_send_phrase"): ("str", 64),
    ("model", "whispercpp_model"): ("str", 4096),
    ("processing", "punctuation_prefix"): ("str", 32),
    ("ai", "base_url"): ("str", 2048),
    ("ai", "model"): ("str", 256),
    ("ai", "api_key_env"): ("str", 128),
    ("ai", "temperature"): ("float", (0.0, 2.0)),
    ("ai", "timeout_seconds"): ("float", (1, 3600)),
    ("insertion", "type_delay_ms"): ("int", (0, 1000)),
    ("insertion", "paste_threshold_chars"): ("int", (1, 1_000_000)),
    ("sounds", "volume"): ("float", (0.0, 1.0)),
    ("history", "audio_budget_gb"): ("float", (0.0, 1024.0)),
}
SETTING_ENUMS: dict[tuple[str, str], set] = {
    ("recording", "preview_mode"): {"auto", "notify", "overlay"},
    ("recording", "preview_overlay_size"): {"pill", "small", "medium", "large"},
    ("hotkey", "mode"): {"toggle", "hold"},
    ("model", "backend"): {"auto", "faster-whisper", "whisper-torch", "whisper.cpp"},
    ("model", "device"): {"auto", "cuda", "cpu"},
    ("model", "compute"): {"auto", "float16", "int8"},
    ("insertion", "mode"): {"auto", "typed", "paste"},
    ("recording", "command"): {"auto", "pw-record", "parecord"},
    ("recording", "spoken_send_key"): {"enter", "shift+enter", "ctrl+enter"},
}
SETTING_BOOLS = {("general", "copy_to_clipboard"), ("general", "tray_enabled"),
                 ("recording", "pause_media"), ("recording", "preview_enabled"),
                 ("recording", "skip_silent"),
                 ("recording", "spoken_send_enabled"),
                 ("processing", "remove_filler_words"),
                 ("processing", "punctuation_enabled"),
                 ("processing", "gaav_enabled"),
                 ("processing", "gaav_lowercase_first"),
                 ("processing", "gaav_remove_trailing_period"),
                 ("ai", "enabled"), ("sounds", "enabled"),
                 ("notifications", "enabled"),
                 ("history", "save"), ("history", "save_audio"),
                 ("model", "eager_warmup")}
# list-valued pass-through keys the UI owns
SETTING_LISTS = (("processing", "filler_words"), ("processing", "dictionary"),
                 ("hotkey", "modifiers"))
ALLOWED_SETTINGS: dict[str, set] = {
    "general": {"language", "copy_to_clipboard", "tray_enabled"},
    "hotkey": {"key", "modifiers", "mode", "cancel_key", "rewrite_key",
               "command_key"},
    "recording": {"command", "device", "max_seconds", "skip_silent",
                  "first_pcm_timeout", "spoken_send_enabled",
                  "spoken_send_phrase", "spoken_send_key",
                  "preview_enabled", "preview_mode", "preview_interval",
                  "preview_min_audio", "preview_bottom_offset",
                  "preview_overlay_size", "pause_media"},
    "model": {"backend", "name", "device", "compute", "whispercpp_model",
              "eager_warmup"},
    "processing": {"remove_filler_words", "filler_words",
                   "punctuation_enabled", "punctuation_prefix", "dictionary",
                   "gaav_enabled", "gaav_lowercase_first",
                   "gaav_remove_trailing_period"},
    "ai": {"enabled", "base_url", "model", "api_key_env", "temperature",
           "timeout_seconds", "max_retries", "per_app_prompts"},
    "insertion": {"mode", "type_delay_ms", "paste_threshold_chars"},
    "sounds": {"enabled", "volume"},
    "notifications": {"enabled"},
    "history": {"save", "save_audio", "audio_budget_gb"},
    "command": {"max_turns", "working_dir", "timeout_seconds",
                "confirm_timeout_s"},
}
RESTART_REQUIRED = {"model.eager_warmup"}
ENGINE_KEYS = {"model.backend", "model.device", "model.compute",
               "model.whispercpp_model"}


def coerce_setting(section: str, key: str, value: Any) -> tuple[bool, Any]:
    """Validate one value. Returns (ok, coerced)."""
    import re as _re

    if (section, key) in SETTING_BOOLS:
        return (isinstance(value, bool), value)
    if (section, key) in SETTING_ENUMS:
        enums = SETTING_ENUMS[(section, key)]
        return (isinstance(value, str) and value in enums, value)
    if (section, key) == ("general", "language"):
        ok = isinstance(value, str) and bool(
            _re.fullmatch(r"auto|[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", value.strip()))
        return (ok, value.strip() if ok else value)
    if (section, key) == ("ai", "per_app_prompts"):
        return _coerce_per_app_prompts(value)
    rule = SETTING_RANGES.get((section, key))
    if rule:
        kind, bound = rule
        if kind == "str":
            ok = isinstance(value, str) and 0 < len(value) <= bound \
                and not value.startswith("-")
            return (ok, value)
        try:
            num = float(value) if kind == "float" else int(value)
            if isinstance(value, bool) or not (bound[0] <= num <= bound[1]):
                return (False, value)
            return (True, num)
        except (TypeError, ValueError):
            return (False, value)
    if (section, key) in SETTING_LISTS:
        if not isinstance(value, list):
            return (False, value)
        if key == "modifiers" and any(m not in ("ctrl", "alt", "shift", "super")
                                      for m in value):
            return (False, value)
        if key == "filler_words" and any(not isinstance(w, str) or len(w) > 64
                                         or not w.strip() for w in value):
            return (False, value)
        if key == "dictionary":
            for entry in value:
                if (not isinstance(entry, dict)
                        or not isinstance(entry.get("triggers", []), list)
                        or not isinstance(entry.get("replacement", ""), str)
                        or len(entry.get("replacement", "")) > 512):
                    return (False, value)
        return (True, value)
    return (False, value)  # unknown key -> reject


def _coerce_per_app_prompts(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, list):
        return (False, value)
    rules = []
    for raw in value[:50]:
        if not isinstance(raw, dict):
            return (False, value)
        apps = [str(a).strip() for a in raw.get("apps", []) if str(a).strip()][:20]
        instructions = str(raw.get("instructions", "")).strip()[:2000]
        if not apps or not instructions:
            return (False, value)
        rules.append({"apps": apps, "instructions": instructions})
    return (True, rules)


def apply_settings(cfg: dict, body: dict) -> tuple[list[str], list[str]]:
    """Whitelisted, validated merge of {section: {key: value}} into cfg
    (mutates cfg; no save). Returns (changed, rejected) as 'section.key'
    strings. Unknown keys and bad types are rejected, never half-applied."""
    from . import backends

    changed: list[str] = []
    rejected: list[str] = []
    for section, keys in ALLOWED_SETTINGS.items():
        for key in keys:
            if section in body and key in body[section]:
                value = body[section][key]
                if (section, key) == ("model", "name"):
                    value = backends.ALIASES.get(str(value).strip().lower(),
                                                 str(value).strip().lower())
                    ok = value in backends.FW_MODEL_REPOS or value == "auto"
                elif (section, key) == ("ai", "max_retries"):
                    try:
                        ok = isinstance(value, (int, float)) \
                            and not isinstance(value, bool) \
                            and 0 <= int(value) <= 10
                        value = int(value)
                    except (TypeError, ValueError):
                        ok = False
                else:
                    ok, value = coerce_setting(section, key, value)
                if not ok:
                    rejected.append(f"{section}.{key}")
                    continue
                if cfg.get(section, {}).get(key) != value:
                    changed.append(f"{section}.{key}")
                cfg.setdefault(section, {})[key] = value
    return changed, rejected


def mask_secrets(cfg: dict) -> dict:
    """Deep copy with secrets replaced by booleans (api-key rule)."""
    safe = copy.deepcopy(cfg)
    key = safe.get("ai", {}).get("api_key", "")
    safe.setdefault("ai", {})["api_key"] = bool(key)
    return safe
