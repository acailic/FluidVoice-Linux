# FluidVoiceLinux — Status Ledger

Last updated: 2026-09-02 · v0.1.0 · **235 automated tests** (233 offline + 2 E2E)
· verified against upstream `altic-dev/FluidVoice` by a 5-agent audit
(prompts/AI, punctuation rules, daemon pipeline, models, security).

Companion docs: [BEHAVIOR-SPEC.md](BEHAVIOR-SPEC.md) (what upstream does,
with file:line evidence) · [ROADMAP.md](ROADMAP.md) (the forward plan) ·
[COMPARISON.md](COMPARISON.md) (vs. other Linux dictation tools).

---

## ✅ Done and verified

### Core dictation loop (live-tested on Pop!_OS X11)
- Global hotkey via XGrabKey: **toggle** mode with any keysym (modifier-only
  keys like Right Ctrl included, lock-mask variants handled) and **hold**
  (push-to-talk) for non-modifier keys; optional second cancel key.
- Recording through PipeWire (`pw-record`) / PulseAudio (`parecord`), 16 kHz
  mono s16 WAV, configurable device; SIGINT→SIGTERM→SIGKILL stop escalation;
  stderr drained to avoid pipe blocking.
- Transcription on **faster-whisper with CUDA** (auto-falls back to CPU int8);
  torch-whisper and whisper.cpp backends; auto-selection priority; models
  tiny→large-v3-turbo (auto: small on GPU / base on CPU), background
  download + hot-swap; upstream `whisper-*` names accepted.
- Text insertion: `xdotool type` (clipboard-free) or clipboard paste with
  restore; auto-paste for long texts; leading-dash guard; clipboard fallback.
- Watchdogs: max-duration auto-stop (300 s), **first-PCM timeout** (2 s —
  muted/wrong mic fails fast), silence gate (opt-in, upstream thresholds),
  sub-1s zero padding, stale `/tmp` sweep at startup, auto-stop race guard.
- Stop/start SFX (the original GPLv3 upstream sounds), desktop notifications,
  history JSONL (5000-entry cap, efficient tail, optional audio retention
  with GB budget), `paste-last`, optional copy-to-clipboard.

### Text processing (upstream-faithful, audit-verified)
- Filler removal — upstream split/trim semantics, default word list identical.
- Custom dictionary — case-insensitive, longest-first, boundaries only on
  word-char edges.
- Spoken punctuation (`literal comma`, …) — **matches upstream's LIVE rule
  table**: all 108 aliases (incl. parentheses/curly/angle/quote variants,
  `plus`, `equal`, `equals`), `double quote` toggling, longest-alias-first
  matching (`dot dot dot` beats `dot`), upstream spacing semantics per symbol,
  and the real cleanup passes (comma sandwiched between symbols; comma before
  `%` after a digit; original-text trailing period before formatting actions).
  *Fidelity note: upstream's dot/slash/at-sign "context gates" are dead code —
  the shipping app applies rules unconditionally; so do we.*

### AI polish (audit-verified byte-identical prompts)
- All five upstream prompts copied **byte-identical** (verified with Swift
  multiline semantics).
- One-user-message folding with `${transcript}` placeholder support.
- Request params faithful: temperature omitted for reasoning/claude-5-family
  models, `reasoning_effort` (gpt-5*/o1/o3/o4/gpt-oss) and `enable_thinking`
  (nemotron/deepseek-reasoner), OpenAI **Responses API** support,
  think-tag stripping with the opening-tag guard, empty-response error.
- Works with any OpenAI-compatible endpoint (OpenAI/Groq/Ollama/LM Studio/
  llama.cpp); live-tested against local Ollama.
- Error behavior: AI failure falls back to raw transcript + notification.

### Settings web UI (`fluidvoice settings`, 127.0.0.1:47735)
- Model picker (sizes verified against the actual HF artifacts, download
  state, one-click switch with rollback on failure and double-spawn guard).
- AI config with live Test-connection; hotkey/mode/language/insertion/
  processing toggles; history view; live status (recording/backend/GPU).
- **Security-hardened** (audit-driven, live-verified): Host allowlist +
  Origin check + JSON-only POSTs + 64 KB body cap (CSRF/DNS-rebinding),
  API key never sent to non-saved hosts, XSS escaping of window titles,
  config written 0600 atomically, full type/range validation of POSTed
  config, secrets carried over on save and masked in GET.

### Infrastructure
- CLI: `daemon / toggle / cancel / status / paste-last / transcribe / history
  / config / settings / doctor`; unix-socket control protocol.
- systemd user unit (DISPLAY/XAUTHORITY aware, tied to graphical session);
  installer generates it with real paths and enables it.
- Python 3.11+, GPLv3, published as the `linux` branch of the fork
  `acailic/FluidVoice`.

---

## ⚠️ Intentional divergences (documented decisions)

| Divergence | Why |
|---|---|
| 429/5xx HTTP responses are retried (upstream never retries HTTP errors) | resilience for rate-limited local/remote endpoints |
| Thinking-only model answers fall back to the raw transcript (upstream types the raw content) | never type `<think>` junk |
| AI timeout 120 s (upstream: 30 s streaming / 120 s non-streaming) | we are non-streaming; big local models are slow |
| `max_seconds` cap (upstream: none) | runaway-recording safety; configurable |
| Hold mode grabs the whole keyboard during the hold | X11 limitation of seeing KeyRelease; fix is roadmap |
| No telemetry at all (upstream has opt-in analytics) | privacy-first choice |

---

## 🚧 Left (see ROADMAP.md for details and upstream references)

### Near term — daily-driver polish (v0.2)
- [ ] **Live streaming preview** overlay (rolling transcription while speaking).
- [ ] **Rewrite/Write mode** — selection capture, edit prompts (already
      ported verbatim), dedicated hotkey.
- [ ] Hold-mode key passthrough (other keys interrupt, not swallow).
- [ ] Spoken-send ("send it" auto-stop + Enter with VAD countdown).
- [ ] Per-app prompt sets and user-editable prompt profiles.
- [ ] Per-model language selection (one global language today).

### Wayland parity (v0.3)
- [ ] Insertion via ydotool/wtype; wl-clipboard restore; DE-shortcut /
      evdev hotkey paths.

### Models (v0.4)
- [ ] **Parakeet TDT v2/v3 via NeMo/ONNX** — upstream's default model and the
      highest-value addition on NVIDIA.
- [ ] Parakeet Realtime / Nemotron 3.5 streaming (NeMo/Riva) — unlocks real
      streaming preview.
- [ ] whisper.cpp GGUF auto-download; model manager.

### Later
- [ ] Command mode (voice → terminal agent, upstream tool schema + confirmations).
- [ ] GAAV + continuous-dictation formatting (needs caret text via AT-SPI).
- [ ] Slash-command/mention literal formatting + terminal autocomplete spacing.
- [ ] Insertion hardening: paste verification, transient clipboard marks,
      per-app paste quirks, AT-SPI fallback.
- [ ] Input-device monitoring / Bluetooth auto-switch; MPRIS media pause.
- [ ] Dictionary auto-learning; audio ZIP export; usage stats; onboarding;
      updater; local OpenAI-style HTTP API; packaging (AUR/nix/deb/pipx).

### Non-goals
- Cohere Transcribe (CoreML-only artifacts, no Linux runtime).
- Bundling a closed-source "Fluid Intelligence" (use any local LLM server).
- macOS support. Telemetry.

---

## Test & verification status

| Area | Verification |
|---|---|
| Processing engines (punctuation/fillers/dictionary) | 60+ unit tests incl. upstream-fidelity cases |
| AI client (params/endpoints/think-strip/retries) | unit tests with mocked transport + live Ollama session |
| Daemon state machine & pipeline | stub-based tests (toggle/cancel/busy/watchdogs/races) |
| Web UI API + security | endpoint tests + CSRF/rebinding/validation matrix + live curl checks |
| Recorder / insertion / history / backends | stub or subprocess-mock tests |
| End-to-end speech | JFK sample through GPU transcription (pytest `-m slow`) |
| Live hardware loop | mic→GPU transcription via speaker playback; hotkey grab on X11; acoustic JFK transcription verified verbatim |
