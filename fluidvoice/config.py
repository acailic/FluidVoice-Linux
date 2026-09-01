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
    },
    "hotkey": {
        # X11 keysym name. Modifier-only keys (Right_Control, Right_Alt,
        # Right_Shift, Super_R...) work in "toggle" mode only.
        "key": "Right_Control",
        "modifiers": [],  # any of: ctrl, alt, shift, super
        "mode": "toggle",  # toggle | hold (hold needs a non-modifier key)
        "cancel_key": "",  # optional extra keysym that cancels recording
    },
    "recording": {
        "command": "auto",  # auto | pw-record | parecord
        "device": "",  # optional PipeWire target / PulseAudio device
        "max_seconds": 300,
        "skip_silent": False,  # skip obviously-silent recordings <= 4s
        "sample_rate": 16000,
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
    },
    "ai": {
        # OpenAI-compatible chat endpoint (OpenAI, Groq, Ollama /v1, LM Studio, llama.cpp server...)
        "enabled": False,
        "base_url": "http://localhost:11434/v1",
        "model": "",
        "api_key": "",  # preferred: leave empty and use api_key_env
        "api_key_env": "FLUIDVOICE_API_KEY",
        "temperature": 0.2,
        "timeout_seconds": 60,
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
    return _deep_merge(DEFAULTS, user)


TEMPLATE = """\
# FluidVoiceLinux configuration.
# Delete any line to fall back to the built-in default.

[general]
# Whisper language code ("auto" detects, or "en", "de", ...)
language = "auto"

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
timeout_seconds = 60
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


def write_template(path: Path | None = None) -> Path:
    path = path or paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE)
    return path
