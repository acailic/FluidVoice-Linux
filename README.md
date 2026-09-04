<p align="center">
  <img src="fluidvoice/assets/icon.png" width="128" alt="SayItErmano app icon">
</p>

<h1 align="center">SayItErmano</h1>

<p align="center">
  <strong>Dictation app for Linux</strong> — press a key, speak, and polished text lands in any app.<br>
  100% local speech-to-text · optional AI polish · native GTK 4 app
</p>

<p align="center">
  <a href="https://github.com/acailic/SayItErmano/releases"><img src="https://img.shields.io/github/v/release/acailic/SayItErmano?color=blue&label=release" alt="latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/acailic/SayItErmano?color=blue" alt="license GPL-3.0"></a>
  <img src="https://img.shields.io/badge/tests-558%20passing-brightgreen" alt="558 automated tests">
  <img src="https://img.shields.io/badge/platform-Linux%20%C2%B7%20X11%20%C2%B7%20GTK%204-blue" alt="Linux · X11 · GTK 4">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
</p>

<p align="center">
  <img src="docs/screenshots/demo.gif" width="740" alt="animated demo: press Right Ctrl, the pill shows a live waveform and streaming transcription, then the polished sentence is typed into the chat app">
</p>

> [!NOTE]
> This is an **unofficial, community port** of [FluidVoice](https://github.com/altic-dev/FluidVoice)
> — the free, open-source, on-device dictation app for macOS — to Linux. It is
> not built by the FluidVoice authors: the macOS app is Swift/Xcode, this is a
> Python implementation of the same behavior and, where licensed to do so
> (GPLv3), the same prompts, rules and sounds. See
> [docs/BEHAVIOR-SPEC.md](docs/BEHAVIOR-SPEC.md) for what was ported, with
> file:line evidence from the upstream sources.
>
> **Naming:** the project, repo, package, command and env-var overrides
> (`SAYITERMANO_CONFIG`, `SAYITERMANO_SOCKET`, `SAYITERMANO_API_KEY`, …) are
> **SayItErmano** (`sayit-ermano`). Only the Python module keeps the upstream
> `fluidvoice` naming on purpose — internals credit the port's origin.
> Installing `sayit-ermano` replaces the pre-rename `fluidvoice-linux` package
> and takes over its config, history and models.

## What's new

**[v0.4.0](https://github.com/acailic/SayItErmano/releases/tag/v0.4.0)** — the
SayItErmano identity: repo, .deb package, command, launcher and tray entry all
carry the new name, plus an **original app icon** (gold tile, speech bubble +
waveform — no FluidVoice artwork anywhere). One-shot installer now defaults to
a user-space install with no sudo.

## How it works

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

### Quick start — one-shot installer

One download + one command, then SayItErmano appears in your app launcher,
autostarts at login, and needs no terminal. The default install is
**user-space and needs no sudo at all** (`~/.local/…` + a systemd user unit
that shadows any system unit); it only asks for sudo if a required system
package (GTK/pygobject, xdotool, …) is missing:

```bash
curl -fsSL https://raw.githubusercontent.com/acailic/SayItErmano/linux/scripts/install-one-shot.sh | bash
```

Prefer the classic system-wide .deb (root-owned, `/opt` runtime)?

```bash
curl -fsSL https://raw.githubusercontent.com/acailic/SayItErmano/linux/scripts/install-one-shot.sh | bash -s -- --system
```

### Manual download

```bash
curl -LO https://github.com/acailic/SayItErmano/releases/download/v0.4.0/sayit-ermano_0.4.0-2_amd64.deb
sudo apt install ./sayit-ermano_0.4.0-2_amd64.deb
```

Grab a specific version from the [releases page](https://github.com/acailic/SayItErmano/releases),
or build it yourself: `git clone … -b linux && ./packaging/build-deb.sh`.

**What you get after install** (log out/in once):

- **App launcher entry "SayItErmano"** (opens the native app) with its own icon
- **Daemon autostarts at login** (XDG autostart; a systemd user unit is also
  provided: `systemctl --user enable --now sayit-ermano`)
- `sayit-ermano` available everywhere in PATH (`doctor`, `toggle`,
  `settings`, `history`, …)
- Removes cleanly with `sudo apt remove sayit-ermano` — upgrading from the
  pre-rename `fluidvoice-linux` package replaces it automatically; your
  config, history and downloaded models are kept

### From source (development)

```bash
git clone https://github.com/acailic/SayItErmano.git -b linux
cd SayItErmano
./scripts/install.sh          # apt deps + venv (reuses your CUDA torch if present)

# run it (foreground; systemd unit in systemd/)
.venv/bin/sayit-ermano daemon
```

Press **Right Ctrl**, speak, press **Right Ctrl** again. Done.

Useful commands:

```bash
sayit-ermano app               # native GTK app: History, Settings, onboarding
sayit-ermano doctor            # environment check
sayit-ermano toggle            # CLI trigger (bind to a DE shortcut on Wayland)
sayit-ermano cancel            # abort a recording
sayit-ermano transcribe x.opus --json   # one-shot file transcription
sayit-ermano history -n 10
sayit-ermano config init       # write ~/.config/sayit-ermano/config.toml
```

### Requirements

- **X11 session** (full experience: global hotkey + typing into apps). On
  **Wayland**, the daemon still works if you bind a desktop-environment
  shortcut to `sayit-ermano toggle`, but text insertion needs `ydotool`/`wtype`
  (not implemented yet — see roadmap).
- Python 3.11+ (tested 3.12), `pipewire` (`pw-record`), `xdotool`, `xclip`,
  `libnotify-bin`, `pulseaudio-utils` (sounds).
- A whisper model is downloaded on first use (~75 MB tiny … ~3.1 GB large-v3;
  default `small` ≈ 484 MB, or `base` on CPU). For the whisper.cpp backend,
  the curated GGUF models are one-click downloads in Settings → Models.
- GPU is optional: faster-whisper uses CUDA automatically when cuBLAS 12 +
  cuDNN 9 are resolvable; otherwise it falls back to CPU int8.

## The native app

<p>
<img src="docs/screenshots/history-window.png" width="380" alt="History window: status header, search, entry list with replay">
</p>

<p>
<img src="docs/screenshots/settings-general.png" width="292" alt="Settings: General">
<img src="docs/screenshots/settings-models.png" width="292" alt="Settings: Models with one-click switch and GGUF downloads">
<img src="docs/screenshots/settings-ai.png" width="292" alt="Settings: AI polish">
</p>
<p>
<img src="docs/screenshots/settings-dictation.png" width="292" alt="Settings: Dictation with hotkey capture and mic picker">
<img src="docs/screenshots/settings-history.png" width="292" alt="Settings: History retention">
<img src="docs/screenshots/settings-about.png" width="292" alt="Settings: About">
</p>

`sayit-ermano app` opens a native GTK 4 / libadwaita app (single instance;
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
config file directly (applies on next daemon start). Everything it saves goes
to the same `config.toml` (with a strict whitelist; API keys are never exposed
through the UI — use the env var). Settings talk to the daemon over the
user-owned unix control socket — no network listener exists. The config file
is written with 0600 permissions.

### Enable AI polish (optional)

```toml
[ai]
enabled  = true
base_url = "http://localhost:11434/v1"   # Ollama; or OpenAI/Groq/LM Studio
model    = "qwen3:8b"                    # pick a general-purpose chat model
```

With Ollama: `ollama pull qwen3:8b`. No key needed for local endpoints; for cloud
providers set `api_key_env = "SAYITERMANO_API_KEY"` and export the variable
(keys are never written to disk by the tooling).

### Command mode (voice → terminal agent)

Set `command_key` under `[hotkey]` to a spare keysym (e.g. `F10`); like the
rewrite key it needs `[ai]` enabled with a base URL and model. Press it and
dictate an instruction ("list the biggest files in my downloads folder");
stop the recording with the main dictation key. The model then proposes one
shell command at a time — shown in the pill overlay in an
awaiting-confirmation state — and you press the command hotkey again to run
it; `Escape` cancels. Every command requires that explicit confirmation
before anything executes; output is fed back to the model and the loop
continues (bounded by `[command] max_turns`). The `[command]` section also
tunes `working_dir`, `timeout_seconds` and `confirm_timeout_s`; executed
commands are recorded in History.

<details>
<summary><strong>File transcription</strong> (<code>sayit-ermano transcribe</code>)</summary>

Accepts **wav, flac, mp3, opus, oga, ogg, m4a, aac, wma, aiff, webm** (verified
to decode via PyAV). Unknown extensions are still attempted: anything PyAV
can't open is converted with **ffmpeg** to 16 kHz mono WAV first
(`sudo apt install ffmpeg` if it's missing). The whisper.cpp backend always
converts via ffmpeg since `whisper-cli` reliably reads WAV only.

- `--json` prints `{text, language, duration_s, segments}` where `segments`
  are raw `{start, end, text}` per-segment entries with timestamps
  (not post-processed; `[]` on the whisper.cpp backend — segment parsing
  isn't wired up there in v1).
- `--out PATH` writes the result to a file instead of stdout (JSON with
  `--json`); missing parent directories are created.
- Inputs over 25 MB warn: transcription is **not chunked** in v1 and may be
  slow/memory-heavy — shrink first with
  `ffmpeg -i in.opus -ar 16000 -ac 1 out.wav`.

</details>

## Features vs. upstream FluidVoice

| Feature | macOS (upstream) | Linux port (SayItErmano) |
|---|---|---|
| Push hotkey → dictate → text in any app | ✅ (Right ⌥) | ✅ (Right Ctrl / any key) |
| 100% local transcription | ✅ (Parakeet/Nemotron/Whisper/Apple) | ✅ (faster-whisper/whisper.cpp; Parakeet on roadmap) |
| Toggle & hold (push-to-talk) modes | ✅ | ✅ toggle; hold for non-modifier keys (other keys pass through while held) |
| Filler-word removal + custom dictionary | ✅ | ✅ (same defaults) |
| Spoken punctuation ("literal comma") | ✅ full rule table | ✅ ported (dot/slash/at-sign contexts included) |
| AI polish with the original prompt | ✅ (local Fluid Intelligence or cloud) | ✅ (any OpenAI-compatible endpoint; no bundled local LLM yet) |
| Start/stop sounds | ✅ | ✅ (same GPLv3 SFX) |
| Live streaming preview overlay | ✅ | ✅ Mac-style pill (live waveform, mode accent colors, state labels, send indicator) |
| Write/Rewrite selected text | ✅ (⌥R) | ✅ dedicated rewrite hotkey |
| Command mode (voice → terminal agent) | ✅ (notch chat panel) | ✅ dedicated hotkey, live conversation panel, JSON agent loop |
| Per-app prompt sets | ✅ | 🚧 roadmap (app hint is already captured) |
| Settings UI with model picker | ✅ | ✅ native GTK app (`sayit-ermano app`): Settings + History windows |
| Onboarding (setup + tryout) | ✅ | ✅ opens once on first launch (`sayit-ermano app --onboard`) |
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

## Configuration

Everything lives in `~/.config/sayit-ermano/config.toml` (generated by
`sayit-ermano config init`; full commented template). Highlights:

```toml
[hotkey]
key = "Right_Control"       # any keysym: F9, space, Pause, right_alt...
mode = "toggle"             # or "hold" (push-to-talk; other keys pass through while held)

[model]
name = "small"              # tiny/base/small/medium/large-v3/large-v3-turbo
# backend = "whisper.cpp"    # use the external whisper-cli binary instead
whispercpp_model = "ggml-base.bin"  # catalog name or path — download via Settings → Models
device = "auto"             # auto | cuda | cpu

[recording]
mic_priority = ["bluez", "usb-cam"]  # fallback order when the chosen mic vanishes
# (Bluetooth headset first, then a USB webcam; switch never happens mid-take)

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
.venv/bin/python -m pytest tests -m "not slow and not integration"  # unit: offline, fast
.venv/bin/python -m pytest tests -m "integration and not desktop"   # real subsystems, deterministic
.venv/bin/python -m pytest tests -m desktop                          # live session (grabs, pixels)
.venv/bin/python -m pytest tests -m "not desktop"                    # deterministic everything
```

The test pyramid — **558 automated tests** at v0.4.0:

| Layer | What it exercises | Count |
|---|---|---|
| Unit | processing engines, AI client (mocked transport), daemon state machine (stubs), insertion command construction, config validation (apply_settings), overlay/pill painting, GTK app offscreen smoke tests | 527 |
| E2E (slow) | real whisper model transcribing the JFK sample | 2 |
| Integration | real `pw-record` capture + raw→WAV, GPU transcription, streaming preview with the loaded model, a real daemon **subprocess** (socket control incl. get/set-config + select-model, toggle/cancel, clean shutdown), live X11 hotkey grab + overlay pixel proof, real CLI invocations (doctor/transcribe/history/config), live AI polish + rewrite against local Ollama (skipped when absent), .deb extract + relocated-venv import, one-shot installer DRY_RUN download | 29 |

Integration tests run against your real PipeWire/X11/CUDA environment and are
isolated through `SAYITERMANO_CONFIG` / `SAYITERMANO_SOCKET` / `XDG_DATA_HOME`
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
- "FluidVoice" is the upstream project's name; SayItErmano is this
  community-maintained Linux port of it and is not affiliated with or
  endorsed by altic-dev.
