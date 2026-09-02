# FluidVoice for Linux

**Community Linux port of [FluidVoice](https://github.com/altic-dev/FluidVoice)** — the free,
open-source, on-device voice dictation app. Press a hotkey, speak, press it again:
your speech becomes polished text typed into whatever app has focus. 100% local
speech-to-text; optional AI polish via any OpenAI-compatible endpoint (including
a local Ollama).

> This is an **unofficial** port of FluidVoice's *behavior* to Linux. It is not
> built by the FluidVoice authors. The macOS app is Swift/Xcode; Linux gets a
> Python implementation of the same ideas and, where licensed to do so (GPLv3),
> the same prompts, rules and sounds. See [docs/BEHAVIOR-SPEC.md](docs/BEHAVIOR-SPEC.md)
> for what was ported from the upstream source.

[![Status](https://img.shields.io/badge/status-v0.1%20MVP-green)]() [![License](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

## What it does

1. **Global hotkey** (default: Right Ctrl, toggle mode) starts recording — 16 kHz mono via PipeWire.
2. **Local transcription** — faster-whisper on CUDA GPU when available, CPU int8 otherwise (whisper.cpp and torch backends also supported).
3. **Post-processing chain** — filler-word removal → custom dictionary → **spoken punctuation commands** (`literal comma`, `literal new line`, `example literal dot com`, …) — the full FluidVoice rule table.
4. **Optional AI polish** — the *verbatim* FluidVoice dictation prompt sent to any OpenAI-compatible endpoint (OpenAI, Groq, Ollama, LM Studio, llama.cpp server). Turns *"um lets meet on tuesday around 3 no wait 4 p.m."* into *"Let's meet on Tuesday at 4 p.m."*
5. **Text insertion** — `xdotool type` keystrokes (clipboard-free), or clipboard paste with automatic restore for long texts. Plus history, start/stop sounds (the original GPLv3 FluidVoice SFX), and desktop notifications.

```
hotkey ─▶ pw-record 16k mono ─▶ faster-whisper (CUDA/int8) ─▶ fillers/dictionary/
                                                                spoken-punctuation
                                                                        │
        typed into focused app ◀─ xdotool type / paste+restore ◀─ optional AI polish
                                                  (OpenAI-compatible / Ollama)
```

## Quick start (X11: Pop!_OS/Ubuntu/Debian)

```bash
git clone https://github.com/acailic/FluidVoice.git -b linux
cd FluidVoice
./scripts/install.sh          # apt deps + venv (reuses your CUDA torch if present)

# run it (foreground; systemd unit in systemd/)
.venv/bin/fluidvoice daemon
```

Press **Right Ctrl**, speak, press **Right Ctrl** again. Done.

Useful commands:

```bash
fluidvoice settings          # open the settings web UI (model picker, AI config...)
fluidvoice doctor            # environment check
fluidvoice toggle            # CLI trigger (bind to a DE shortcut on Wayland)
fluidvoice cancel            # abort a recording
fluidvoice status --json
fluidvoice transcribe x.wav  # one-shot transcription
fluidvoice history -n 10
fluidvoice config init       # write ~/.config/fluidvoice/config.toml
```

### Settings UI

`fluidvoice settings` opens a local web page (127.0.0.1 only, served by the
daemon) that mirrors the macOS app's settings window:

- **Speech models** — cards for tiny → large-v3-turbo with sizes and download
  state; one click switches (and downloads) the active model.
- **AI polish** — enable/configure any OpenAI-compatible endpoint with a
  live "Test connection" button.
- **Dictation** — hotkey, mode, language, insertion strategy, filler/punctuation
  toggles.
- **History** — your recent transcriptions.

Everything it saves goes to the same `config.toml` (with a strict whitelist;
API keys are never exposed through the UI — use the env var). The page is
hardened against cross-site requests (Host/Origin checks, JSON-only POSTs,
64 KB body cap) and the stored key is only ever attached to the endpoint host
you saved — a website can't use it as an exfiltration relay. The config file
is written with 0600 permissions.

### Enable AI polish (optional)

```toml
[ai]
enabled  = true
base_url = "http://localhost:11434/v1"   # Ollama; or OpenAI/Groq/LM Studio
model    = "qwen3:8b"                    # pick a general-purpose chat model
```

With Ollama: `ollama pull qwen3:8b`. No key needed for local endpoints; for cloud
providers set `api_key_env = "FLUIDVOICE_API_KEY"` and export the variable
(keys are never written to disk by the tooling).

## Features vs. upstream FluidVoice

| Feature | macOS (upstream) | Linux port v0.1 |
|---|---|---|
| Push hotkey → dictate → text in any app | ✅ (Right ⌥) | ✅ (Right Ctrl / any key) |
| 100% local transcription | ✅ (Parakeet/Nemotron/Whisper/Apple) | ✅ (faster-whisper/whisper.cpp; Parakeet on roadmap) |
| Toggle & hold (push-to-talk) modes | ✅ | ✅ toggle; hold for non-modifier keys |
| Filler-word removal + custom dictionary | ✅ | ✅ (same defaults) |
| Spoken punctuation ("literal comma") | ✅ full rule table | ✅ ported (dot/slash/at-sign contexts included) |
| AI polish with the original prompt | ✅ (local Fluid Intelligence or cloud) | ✅ (any OpenAI-compatible endpoint; no bundled local LLM yet) |
| Start/stop sounds | ✅ | ✅ (same GPLv3 SFX) |
| Live streaming preview overlay | ✅ | 🚧 roadmap |
| Write/Rewrite selected text | ✅ (⌥R) | 🚧 roadmap (X11 selection via xclip) |
| Command mode (voice → terminal agent) | ✅ | 🚧 roadmap |
| Per-app prompt sets | ✅ | 🚧 roadmap (app hint is already captured) |
| Settings UI with model picker | ✅ | ✅ local web UI (`fluidvoice settings`) |
| Notch overlay / menu bar | ✅ | ➖ N/A on Linux; notifications today |

See [docs/STATUS.md](docs/STATUS.md) for the full done/left ledger (verified
by a 5-agent audit against the upstream Swift sources),
[docs/COMPARISON.md](docs/COMPARISON.md) for how this relates to other Linux
dictation tools (Handy, Vocalinux, nerd-dictation, …) and
[docs/ROADMAP.md](docs/ROADMAP.md) for the forward plan.

## Requirements

- **X11 session** (full experience: global hotkey + typing into apps).
  On **Wayland**, the daemon still works if you bind a desktop-environment
  shortcut to `fluidvoice toggle`, but text insertion needs `ydotool`/`wtype`
  (not implemented yet — see roadmap).
- Python 3.10+ (tested 3.12), `pipewire` (`pw-record`), `xdotool`, `xclip`,
  `libnotify-bin`, `pulseaudio-utils` (sounds).
- A whisper model is downloaded on first use (~75 MB tiny … ~3.1 GB large-v3;
  default `small` ≈ 484 MB, or `base` on CPU).
- GPU is optional: faster-whisper uses CUDA automatically when cuBLAS 12 +
  cuDNN 9 are resolvable (the installer reuses the NVIDIA pip packages that
  ship with a CUDA torch install); otherwise it falls back to CPU int8.

## Configuration

Everything lives in `~/.config/fluidvoice/config.toml` (generated by
`fluidvoice config init`; full commented template). Highlights:

```toml
[hotkey]
key = "Right_Control"       # any keysym: F9, space, Pause, right_alt...
mode = "toggle"             # or "hold" (push-to-talk, non-modifier keys)

[model]
name = "small"              # tiny/base/small/medium/large-v3/large-v3-turbo
device = "auto"             # auto | cuda | cpu

[processing]
dictionary = [ { triggers = ["miro board"], replacement = "Miro board" } ]

[insertion]
mode = "auto"               # typed | paste | auto (paste for long texts)
```

## Development

```bash
.venv/bin/python -m pytest -m "not slow"   # unit tests (no network)
.venv/bin/python -m pytest -m slow         # E2E: downloads tiny model + JFK sample
```

Layout: `fluidvoice/backends/` (speech engines) · `processing/` (fillers,
dictionary, spoken punctuation) · `ai/` (prompts + OpenAI-compatible client) ·
`insertion.py` · `hotkey.py` (XGrabKey) · `control.py` (unix socket) ·
`daemon.py` (orchestration).

## License & credits

- **GPL-3.0** — same license as upstream. The dictation/edit prompts and the
  start/stop sounds are copied from [altic-dev/FluidVoice](https://github.com/altic-dev/FluidVoice)
  (GPLv3). Huge thanks to the FluidVoice authors for open-sourcing it.
- Speech by [faster-whisper](https://github.com/SYstran/faster-whisper) (MIT) /
  [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT) /
  [OpenAI Whisper](https://github.com/openai/whisper) (MIT).
- "FluidVoice" is the upstream project's name; this fork's Linux port is
  community-maintained and not affiliated with or endorsed by altic-dev.
