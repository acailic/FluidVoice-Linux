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

## Installation

### Option A — .deb package (the "Mac app" experience)

One download + one command, then FluidVoice appears in your app launcher,
autostarts at login, and needs no terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/acailic/FluidVoice-Linux/linux/scripts/install-one-shot.sh | bash
```

Or manually (download + install):

```bash
curl -LO https://github.com/acailic/FluidVoice-Linux/releases/download/v0.1.0/fluidvoice-linux_0.1.0-1_amd64.deb
sudo apt install ./fluidvoice-linux_0.1.0-1_amd64.deb
```

Grab a specific version from the [releases page](https://github.com/acailic/FluidVoice-Linux/releases).
Building it yourself instead: `git clone … -b linux && ./packaging/build-deb.sh`.

What you get after install (log out/in once):
- **App launcher entry "FluidVoice"** (opens the native app) with its own icon
- **Daemon autostarts at login** (XDG autostart; a systemd user unit is also
  provided: `systemctl --user enable --now fluidvoice`)
- `fluidvoice` available everywhere in PATH (`fluidvoice doctor`, `toggle`,
  `settings`, `history`, ...)
- Removes cleanly with `sudo apt remove fluidvoice-linux`

### Option B — from source (development)

```bash
git clone https://github.com/acailic/FluidVoice-Linux.git -b linux
cd FluidVoice-Linux
./scripts/install.sh          # apt deps + venv (reuses your CUDA torch if present)

# run it (foreground; systemd unit in systemd/)
.venv/bin/fluidvoice daemon
```

Press **Right Ctrl**, speak, press **Right Ctrl** again. Done.

Useful commands:

```bash
fluidvoice app               # native GTK app: History, Settings, onboarding
fluidvoice settings          # same app, Settings window (alias)
fluidvoice doctor            # environment check
fluidvoice toggle            # CLI trigger (bind to a DE shortcut on Wayland)
fluidvoice cancel            # abort a recording
fluidvoice status --json
fluidvoice transcribe x.wav  # one-shot transcription
fluidvoice history -n 10
fluidvoice config init       # write ~/.config/fluidvoice/config.toml
```

### Native app

`fluidvoice app` opens a native GTK 4 / libadwaita app (single instance;
follows your system theme) that mirrors the macOS app's windows:

- **History** (main window) — live status header, search, copy/delete,
  inline audio replay for retained recordings.
- **Settings** — General / Models (one-click switch + download) / AI polish
  (any OpenAI-compatible endpoint, live Test connection, per-app prompts) /
  Dictation (hotkeys with press-to-capture, mic picker, live-preview sizes,
  spoken send) / History. Saving hot-applies what the daemon can take live
  (hotkey re-grab, recorder/tray/model rebuild) and says what needs a restart.
- **Onboarding** — opens once on first launch with a real 3-second tryout.

With the daemon stopped, History still works and Settings saves to the
config file directly (applies on next daemon start).

Everything it saves goes to the same `config.toml` (with a strict whitelist;
API keys are never exposed through the UI — use the env var). Settings talk
to the daemon over the user-owned unix control socket — no network listener
exists. The config file is written with 0600 permissions.

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
| Live streaming preview overlay | ✅ | ✅ Mac-style pill overlay (bottom-center, live waveform) |
| Write/Rewrite selected text | ✅ (⌥R) | ✅ dedicated rewrite hotkey |
| Command mode (voice → terminal agent) | ✅ | 🚧 roadmap |
| Per-app prompt sets | ✅ | 🚧 roadmap (app hint is already captured) |
| Settings UI with model picker | ✅ | ✅ native GTK app (`fluidvoice app`): Settings + History windows |
| Onboarding (setup + tryout) | ✅ | ✅ opens once on first launch (`fluidvoice app --onboard`) |
| Overlay sizes (pill/small/medium/large) | ✅ | ✅ `recording.preview_overlay_size` |
| Notch overlay / menu bar | ✅ | ✅ tray/panel icon (StatusNotifierItem): click = dictate, state badge, tooltip with hotkey |

See [docs/STATUS.md](docs/STATUS.md) for the full done/left ledger (verified
by a 5-agent audit against the upstream Swift sources),
[docs/COMPARISON.md](docs/COMPARISON.md) for how this relates to other Linux
dictation tools (Handy, Vocalinux, nerd-dictation, …),
[docs/ROADMAP.md](docs/ROADMAP.md) for the forward plan, and
[docs/UPSTREAM-TRACKING.md](docs/UPSTREAM-TRACKING.md) for the
macOS-vs-Linux capability matrix and the upstream changelog we track
(refresh it with `scripts/upstream-diff.sh`).

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

## Development & testing

**Branch layout:** the port lives on `linux` — treat it as this fork's main
line (all commits, merges, and releases go there). The `main` branch mirrors
the upstream macOS repo for reference only and is **never** updated with port
work; to see what moved upstream, run `scripts/upstream-diff.sh`.

```bash
.venv/bin/python -m pytest -m "not slow and not integration"  # unit: offline, fast
.venv/bin/python -m pytest -m "integration and not desktop"   # real subsystems, deterministic
.venv/bin/python -m pytest -m desktop                          # live session (grabs, pixels)
.venv/bin/python -m pytest -m "not desktop"                    # deterministic everything
```

The test pyramid:

| Layer | What it exercises | Count |
|---|---|---|
| Unit | processing engines, AI client (mocked transport), daemon state machine (stubs), insertion command construction, config validation (apply_settings), GTK app offscreen smoke tests | ~268 |
| E2E (slow) | real whisper model transcribing the JFK sample | 2 |
| Integration | real `pw-record` capture + raw→WAV, GPU transcription, streaming preview with the loaded model, a real daemon **subprocess** (socket control incl. get/set-config + select-model, toggle/cancel, clean shutdown), live X11 hotkey grab + overlay pixel proof, real CLI invocations (doctor/transcribe/history/config), live AI polish + rewrite against local Ollama (skipped when absent), .deb extract + relocated-venv import, one-shot installer DRY_RUN download | 27 |

Integration tests run against your real PipeWire/X11/CUDA environment and are
isolated through `FLUIDVOICE_CONFIG` / `FLUIDVOICE_SOCKET` / `XDG_DATA_HOME`
env overrides (the same overrides work for running multiple daemons).

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
