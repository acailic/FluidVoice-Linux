# Upstream Tracking — macOS FluidVoice vs. the Linux port

This is the canonical ledger for **what macOS FluidVoice can do, whether the
Linux port has it, and what changed upstream lately**. The port's own internal
status lives in [STATUS.md](STATUS.md); this doc faces *upstream*.

- **[Capability matrix](#capability-matrix--what-macos-can-do-vs-linux)** — the
  standing "possible on macOS vs. available on Linux" view.
- **[Upstream changelog](#upstream-changelog-newest-first)** — every upstream
  release (and the unreleased tip), each change tagged with its Linux status.
- **[Tracking loop](#tracking-loop)** — how to refresh this doc; one command.

## Status legend

| Mark | Meaning |
|---|---|
| ✅ | Ported — works on Linux today |
| 🚧 | Planned — on [ROADMAP.md](ROADMAP.md) with a target version |
| ⏳ | Not ported, not on the roadmap yet (candidate — decide: adopt or won't-do) |
| ➖ | N/A on Linux — platform-bound; a substitute is noted where one exists |
| ❓ | Needs triage — looks relevant, verify against our behavior before deciding |

## Baseline

| | |
|---|---|
| Upstream commit | `b60a302` (2026-09-01) — `b60a302197a2018a388a5d4416c78039dfe85647` |
| Latest upstream release | `v1.6.9` (2026-08-18) |
| Port audited against it | 2026-09-02, 5-agent audit + the v0.1.x feature work through `e3bfa37` (295 tests) |
| Machine-readable pin | [upstream-baseline.txt](upstream-baseline.txt) (read by `scripts/upstream-diff.sh`) |

The baseline says: everything upstream through `b60a302` was already considered
by the 2026-09-02 audit and feature work; the statuses below reflect that.
Anything upstream lands *after* `b60a302` is "new and not yet available on
Linux" until triaged here.

## Tracking loop

1. Run `./scripts/upstream-diff.sh` — fetches upstream and prints new commits,
   new tags, and watched Swift sources that changed since the baseline.
2. Triage: give every user-facing change a row in the
   [changelog](#upstream-changelog-newest-first) below with a status mark
   (move 🚧 items onto ROADMAP.md if adopted).
3. Bump the baseline: update the table above **and**
   `docs/upstream-baseline.txt` (`sha`, `short`, `date`, `tag`, `checked`).
4. Commit together: `docs(tracking): upstream <old-short>..<new-short>`.

A quick cadence (e.g. after each upstream release or once a week) keeps "what's
new that Linux doesn't have" a one-command answer.

---

## Capability matrix — what macOS can do vs. Linux

| macOS capability | Linux port | Notes / substitute |
|---|---|---|
| Global push hotkey (Right ⌥) | ✅ | Right Ctrl (any keysym) via XGrabKey; on Wayland bind a DE shortcut to `fluidvoice toggle` |
| Whisper models (tiny→large) | ✅ | faster-whisper (CUDA/int8), whisper.cpp, torch backends |
| Parakeet TDT v2/v3 (upstream default) | 🚧 v0.4 | via NeMo/ONNX; highest-value model addition on NVIDIA |
| Parakeet Flash / Realtime, Nemotron Speech 3.5 (streaming) | 🚧 later | streaming engines also unlock tighter live preview |
| Apple Speech (zero-download) | ➖ | macOS system API; substitute: whisper today, Parakeet in v0.4 |
| Cohere Transcribe | ➖ | non-goal — CoreML-only artifacts, no Linux runtime |
| Fluid Intelligence (bundled local AI) | ➖ | closed-source private runtime; substitute: any OpenAI-compatible endpoint incl. local Ollama ✅ |
| Cloud AI polish (OpenAI/Groq/custom) | ✅ | byte-identical prompts, audit-verified request params |
| Live streaming preview overlay | ✅ | Mac-style pill overlay port (solid-black stadium, gloss border, live-audio waveform, streaming text, processing shimmer), ~1.2 s rolling cadence; notch ➖ N/A |
| Write/Rewrite mode (⌥R) | ✅ | `hotkey.rewrite_key`, verbatim upstream edit prompts |
| Spoken punctuation ("literal …") | ✅ | full live rule table (108 aliases, spacing semantics) |
| Filler removal + custom dictionary | ✅ | same defaults and matching semantics |
| Spoken-send ("send it" → Enter) | ✅ | configurable phrase; upstream's terminal-blocklist not ported ⏳ |
| Command mode (voice → actions) | ⏳ | roadmap "later": voice → terminal agent + confirmations |
| Per-app prompt sets | ⏳ v0.2 | frontmost-app hint already captured |
| Smart typing via accessibility APIs | ✅ / 🚧 | xdotool on X11 ✅; Wayland insertion 🚧 v0.3 (ydotool/wtype); AT-SPI fallback ⏳ |
| Menu bar + notch overlay | ✅ (equivalent) | tray/panel icon via StatusNotifierItem (`tray.py`): click = toggle, right-click = settings, recording badge, tooltip w/ hotkey; notch ➖ N/A |
| Audio history (budget, retention) | ✅ | history JSONL + GB budget; searchable History page w/ inline replay, delete, clear; ZIP export ⏳ |
| Today-usage stats | ⏳ | not started |
| Adaptive light/dark theming | ➖ | settings web UI is plain by design |
| Auto-updates + beta channel | ⏳ | today: .deb / GitHub releases; AUR/nix on roadmap |
| Mic priority list, Bluetooth auto-switch | ⏳ | roadmap: input-device monitoring |
| Speaker labeling (diarization) for file transcription | ⏳ | not started; timestamps/JSON export would come with it |
| API keys in Keychain | ➖ | substitute: `FLUIDVOICE_API_KEY` env var + 0600 config.toml |
| Opt-in telemetry | ➖ | intentionally none (privacy divergence, see STATUS.md) |

## Upstream changelog (newest first)

### Unreleased upstream (after v1.6.9 → `b60a302`, 2026-08-19 → 09-01)

61 commits (incl. merges), grouped by theme:

| Upstream change | Linux | Notes |
|---|---|---|
| Overlay "custom cleanup styles" + streamlined dictation controls (6 commits) | ⏳ | our overlay exists; per-style labels/limits not ported |
| Settings: split AI providers / cleanup styles; side-panel nav; simplified welcome | ➖ | macOS settings chrome; our web UI covers the same knobs |
| Honor "Send Custom Prompt Only" for dictation-shortcut prompt overrides | ⏳ | shortcut prompt overrides not ported at all yet |
| File transcription: chunked API uploads, `.opus`/`.oga` input | ⏳ | `fluidvoice transcribe` handles WAV; opus/oga + chunking not |
| Spoken-send commands, quiet-countdown completion, terminal blocklist | ✅ / ⏳ | spoken-send shipped in our `a1390f5`; terminal blocklist ⏳ |
| Incremental Parakeet preview finalization (experimental) | 🚧 | parakeet-specific; lands with v0.4 streaming work |
| Private AI (Fluid Intelligence) in Edit mode + model verification fixes | ➖ | FI is closed-source; edit mode works with any endpoint ✅ |
| Long-dictation fallback for token-dense Fluid-1 output | ➖ | FI-specific |
| Whisper per-model language picker + `automatic` preserved | ⏳ v0.2 | per-model language selection is on the roadmap |
| Analytics/onboarding-telemetry commits (DAU, weekly buffer, latency capture) | ➖ | no telemetry by design |
| "Instant replacement boost leak" fix | ❓ | verify vs. our dictionary/instant-replacement path |
| CI: archive link on fork PRs | ➖ | upstream CI only |

### v1.6.9 (2026-08-18)

| Upstream change | Linux | Notes |
|---|---|---|
| Custom-dictionary spoken formatting (insert new line/paragraph/tab/punctuation via trigger word) | ❓ | our dictionary does plain replacement only — triage |
| Mic alerts not shown on routine startup + disable option | ⏳ | assumes macOS permission flow |
| Fixes: 3.5mm external mics, Bluetooth route changes, clamshell mode | ⏳ | roadmap: input-device monitoring |
| Speaker-labeled transcription drops no trailing audio | ⏳ | with diarization |

### v1.6.8 (2026-08-11)

| Upstream change | Linux | Notes |
|---|---|---|
| Offline speaker labeling (timestamps, speaker-aware history, text/JSON export) | ⏳ | candidate feature; pyannote-class models exist on Linux |
| Microphone priority list, drag-to-reorder, device history | ⏳ | roadmap: input-device monitoring |
| Fix: modifier-only shortcuts firing after Shift combos | ❓ | we handle lock-mask variants; verify shift-combos |
| Fix: temperature ignored for some OpenAI-compatible models | ✅ | our client always sends temperature (audit-verified) |

### v1.6.7 (2026-08-05)

| Upstream change | Linux | Notes |
|---|---|---|
| Parakeet up to 2× faster on Apple silicon | ➖ | CoreML; our perf work comes with v0.4 ONNX |
| First-word latency ~350 ms → <100 ms | 🚧 | we roll at ~1.2 s; tighter with streaming engines |
| Temporary pasteboard writes hidden from clipboard managers | ⏳ | we restore the clipboard; transient marks are on the roadmap |
| Fix: AirPods media controls stopped while enabled | ⏳ | roadmap: MPRIS media pause |

### v1.6.6 (2026-07-31)

| Upstream change | Linux | Notes |
|---|---|---|
| Faster-appearing recording overlays | ✅ | our overlay window is immediate |
| Optional skip of short silent recordings | ✅ | opt-in silence gate (upstream thresholds) |
| Core Audio default path (sped-up audio fix) | ➖ | PipeWire/PulseAudio here |

### v1.6.5 (2026-07-21)

| Upstream change | Linux | Notes |
|---|---|---|
| Reliable pasting in Ghostty/tmux/terminals | ⏳ | roadmap: insertion hardening (paste verification, quirks) |
| Experimental recording path (now opt-in) | ➖ | macOS capture stack |

### v1.6.4 (2026-07-14)

| Upstream change | Linux | Notes |
|---|---|---|
| Fix Fluid-1 MLX backend on macOS 15 | ➖ | Fluid Intelligence only |

### v1.6.3 (2026-07-14)

| Upstream change | Linux | Notes |
|---|---|---|
| Fluid-1 2.2× faster on Apple silicon | ➖ | Fluid Intelligence only |
| Auto-suggested custom-dictionary replacements | ⏳ | roadmap: dictionary auto-learning |
| Train by Voice (pronunciation samples) | ⏳ | not started |
| Optional/configurable spoken punctuation | ✅ | toggles + full rule table ported |
| All Whisper models restored | ✅ | tiny→large-v3-turbo |
| Copy latest transcript from menu bar | ✅ | `fluidvoice paste-last` + optional copy-to-clipboard |

### v1.6.0 (the release our port was audited against)

| Upstream change | Linux | Notes |
|---|---|---|
| Rebuilt Parakeet ("pretty much zero delay") | 🚧 | v0.4 model work |
| Fluid Intelligence local AI | ➖ | substitute: any OpenAI-compatible endpoint ✅ |
| Adaptive theming + compact toolbar switcher | ➖ | N/A for the web settings UI |
| Refreshed onboarding (engine setup, tryout) | ✅ | `/onboard` web page opens once on first launch: mic/engine/hotkey checks + real 3s dictation tryout (nothing typed) |

---

## Watch: other platforms upstream

- **Windows port** — upstream publishes Windows pre-releases (branch
  `windows-main`, tags through `windows-v0.0.9`, 2026-08-11): redesigned
  overlay with word-by-word live preview, Fluid-1 Mini (1.5 GB local model),
  "learn from your edits" dictionary. Useful signal for what a non-macOS port
  needs; Fluid-1 itself remains closed-source, so the Linux substitute stays
  "bring your own OpenAI-compatible endpoint".
- **iOS** — waitlist only (`altic.dev/fluid/waitlist`); nothing to track yet.
