# SayItErmano — Status Ledger

Last updated: 2026-09-04 · v0.5.0 · **826 automated tests** (794 offline + 32 integration)
· verified against upstream `altic-dev/FluidVoice` by a 5-agent audit
(prompts/AI, punctuation rules, daemon pipeline, models, security).

Companion docs: [BEHAVIOR-SPEC.md](BEHAVIOR-SPEC.md) (what upstream does,
with file:line evidence) · [ROADMAP.md](ROADMAP.md) (the forward plan) ·
[COMPARISON.md](COMPARISON.md) (vs. other Linux dictation tools) ·
[UPSTREAM-TRACKING.md](UPSTREAM-TRACKING.md) (macOS-vs-Linux capability
matrix + upstream changelog with its refresh loop).

---

## ✅ Done and verified

### Core dictation loop (live-tested on Pop!_OS X11)
- Global hotkey via XGrabKey: **toggle** mode with any keysym (modifier-only
  keys like Right Ctrl included, lock-mask variants handled) and **hold**
  (push-to-talk) for non-modifier keys with **native key passthrough**: the
  hold releases the XGrabKey activation (which by X11 semantics grabs the
  whole keyboard for the held key's press-to-release duration), so keys
  typed while holding reach the focused app as real events — no injection;
  release is detected by auto-repeat-proof query_keymap polling, a passive
  Escape grab covers cancel-during-hold, and the hotkey re-arms afterwards
  (an XTEST-replay variant was prototyped and abandoned: live Xorg 21.1
  silently drops XTEST fakes that match the current key state, so replayed
  presses never reach the app); optional second cancel key.
- Recording through PipeWire (`pw-record`) / PulseAudio (`parecord`), 16 kHz
  mono s16 WAV, configurable device; SIGINT→SIGTERM→SIGKILL stop escalation;
  stderr drained to avoid pipe blocking.
- Transcription on **faster-whisper with CUDA** (auto-falls back to CPU int8);
  torch-whisper and whisper.cpp backends; auto-selection priority; models
  tiny→large-v3-turbo (auto: small on GPU / base on CPU), background
  download + hot-swap; upstream `whisper-*` names accepted.
- Text insertion: `xdotool type` (clipboard-free) or clipboard paste with
  restore; auto-paste for long texts; leading-dash guard; clipboard fallback;
  **insertion hardening**: for the duration of a paste FluidVoice owns the
  CLIPBOARD selection (python-xlib) and serves it with clipboard-manager
  hygiene markers, the paste keystroke is verified by observing the target
  read the selection (a 0.25 s quiesce first lets the eager managers reveal
  their windows; 0.6 s cap), and only then is the previous clipboard
  restored — read-back checked, one retry, warning notification on mismatch;
  an unverified paste raises and auto-mode falls back to typed insertion
  with a notification; X11 terminals paste with `ctrl+shift+v`
  (`insertion.terminal_paste_key`, matched via the shared
  `general.terminal_apps` key — `ctrl+v` is passed through to the app in
  terminals; live matrix: gnome-terminal, kitty, alacritty, bare and under
  tmux); `insertion.verify_paste = false` restores the legacy fixed-delay
  behavior; `fluidvoice doctor` reports both keys.
  Insertion-hardening residuals (live-observed, GNOME 46 X11, CopyQ 7.1.0):
  - CopyQ suppression verified live: with `application/x-copyq-secret` /
    `application/x-copyq-hidden` advertised and served, `copyq read 0` is
    unchanged after a marker-tagged hold (the item is silently discarded);
    `x-kde-passwordManagerHint = secret` is also served for
    Klipper/GPaste/KeePassXC semantics, but this CopyQ build does NOT honor
    it (probe-verified: the monitor never fetches the atom — a
    build-without-KGuiAddons quirk).
  - The mutter/gnome-shell selection proxy (used by the enabled
    clipboard-indicator GNOME extension) reads flashed text eagerly at
    ownership change regardless of any marker — a shell-extension history
    capture remains possible; no X11-side fix short of not pasting.
  - GPaste and Klipper are untested (not running on this machine).
  - ghostty is not installed locally — `ctrl+shift+v` there is expected but
    untested; it is covered by the `general.terminal_apps` list.
  - Verify-timeout edge: an app whose own window already read the clipboard
    during the quiesce (its id is in the exclusion set) and whose paste
    lands without a fresh selection read would time out (0.6 s) and re-type
    — the documented trade-off of the read-based verify signal.
- Watchdogs: max-duration auto-stop (300 s), **first-PCM timeout** (2 s —
  muted/wrong mic fails fast), silence gate (opt-in, upstream thresholds),
  sub-1s zero padding, stale `/tmp` sweep at startup, auto-stop race guard.
- Stop/start SFX (the original GPLv3 upstream sounds), desktop notifications,
  history JSONL (5000-entry cap, efficient tail, optional audio retention
  with GB budget), `paste-last`, optional copy-to-clipboard.
- **Live streaming preview** (upstream's headline UX): raw-PCM capture is
  transcribed on a rolling basis while you speak (~1.2 s cadence) and shown
  in a Mac-style pill overlay (bottom-center stadium: live-audio waveform,
  streaming text, processing shimmer; override-redirect, no focus stealing)
  or a replaceable notification; the model is pre-warmed at daemon start.
- **Rewrite/Write mode** (`hotkey.rewrite_key`): captures the selection,
  dictates the instruction, runs the verbatim upstream edit prompts
  (context block, follow-up history, temperature 0.7), types the result.
- **Spoken-send**: trailing "send it" strips and presses Enter afterwards
  ("literal send it" escape honored); configurable phrase/key-combo.
- **GAAV mode**: optional lowercase-first + trailing-period strip for
  search-box/casual dictation.
- **Mic priority list + input-device monitoring** (`recording.mic_priority`):
  a 3 s `pactl list short sources` diff poll notices connects/disconnects;
  when the configured microphone disappears and a priority pattern matches
  (case-insensitive substring, first pattern wins — e.g. `bluez` for a
  Bluetooth headset), FluidVoice switches and notifies. Switching never
  happens mid-dictation (the take finishes on the still-open stream, the
  fallback lands ≤ 3 s after it), `device = ""` (auto) is never overridden,
  and a working device is never preemptively upgraded. Same reselect runs
  once at daemon start (restart while the mic is disconnected → fallback
  instead of a first_pcm_timeout failure). The tray Microphone submenu is
  ordered by the same priority list; the Settings → Dictation page edits it
  (add/move/remove rows).

### Text processing (upstream-faithful, audit-verified)
- Filler removal — upstream split/trim semantics, default word list identical.
- Custom dictionary — case-insensitive, longest-first, boundaries only on
  word-char edges.
- Dictionary auto-learning from History edits (upstream v1.6.3 port) —
  inline repair stamps the pre-edit text as `edited_from` (first edit
  wins) and `processing/dict_learn.py` diffs it against the final text:
  token-level difflib with upstream's shape checks (≤3 words/side, ≤40
  chars/side, ≤70 combined, ≥2 letters/side, purely alphabetic trimmed
  tokens, filler-free, trigger-already-saved suppression —
  Tracker:215-241/676-705); a pair is suggested after 2 occurrences
  (upstream `requiredOccurrences`; counts derive from the history itself
  — one entry = one correction event). Suggest-only Accept/Dismiss rows
  in Settings → Dictation "Suggested words" (nothing enters the
  dictionary without a click — the macOS model; the Windows port
  silently auto-adds); Accept merges through the validated save path
  without duplicate triggers, Dismiss permanent; decisions at
  `~/.config/sayit-ermano/dictionary-suggestions.json`; doctor prints
  the pending count. Divergences in the table below.
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

### Native GTK app (`fluidvoice app` / `fluidvoice settings`)
- GTK 4 + libadwaita, single instance with remote window raising
  (`--open history|settings`, `--onboard`); follows the system theme.
- **History window** (macOS main-window counterpart): live status header
  (state/backend/GPU/model + warmup), search, copy/delete, inline audio
  replay (GtkMediaFile, xdg-open fallback), clear-all, daemon-down banner.
- **Settings window**: every validated key across General / Models /
  AI Polish (+ per-app prompt rules) / Dictation (hotkeys with press-to-
  capture, mic picker, preview, spoken send, GAAV, insertion) / History /
  About; dirty tracking, Ctrl+S, close-with-changes confirm; saves go over
  the control socket and hot-apply (hotkeys re-grab, recorder/tray/model
  rebuild); file-only mode when the daemon is down.
- **whisper.cpp GGUF manager** (Settings → Models): curated catalog of the
  7 `ggerganov/whisper.cpp` ggml models (base…large-v3, multilingual +
  English-only) with streaming one-click download (progress subtitle,
  worker thread + GLib polling, `.part` + atomic rename, no half-written
  files); "Use" switches the backend via validated `set-config`
  (`model.whispercpp_model` accepts a catalog name **or** a path, with
  clear missing/unknown errors); `fluidvoice doctor` reports the binary,
  the resolved model and what's downloaded.
- **Parakeet (ONNX) manager** (Settings → Models): the two curated
  Parakeet TDT exports (v2/v3) with the same download/Use flow (checksum-
  verified atomic model dir); selecting it sets
  `model.backend = "parakeet"` + `model.name` (an engine key — hot-swaps
  the loaded model like `select-model`); doctor reports onnxruntime,
  providers and per-model download state.
- Replaces the retired web UI (spec: docs/superpowers/specs/
  2026-09-02-native-settings-app-design.md) - no TCP listener remains;
  the localhost CSRF/DNS-rebinding surface is gone by construction.
  Validation lives in config.apply_settings (one source of truth), config
  is written 0600 atomically, secrets masked in get-config.

### Infrastructure
- CLI: `daemon / toggle / cancel / status / paste-last / transcribe (multi-format
  + --json/--out) / history
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
| Hold mode passes typed keys through natively but they do NOT end the dictation (upstream clean-tap: other keys interrupt the trigger); the held hotkey's auto-repeat pairs also reach the app | deliberate "keep typing while holding"; X11 has no per-event passthrough under an active grab — releasing the grab entirely is the only clean mechanism (live-verified) |
| No telemetry at all (upstream has opt-in analytics) | privacy-first choice |
| D1: case-only corrections are dictionary candidates (upstream rejects them, `AutomaticDictionaryCorrectionTracker.swift:111`/`:216-227`, test "fluidvoice"→"FluidVoice"→nil) | the canonical documented use of this dictionary is exactly `["miro board"] → "Miro board"` and the engine matches triggers case-insensitively, so a learned case entry is fully functional; threshold-2 + suggest-only + permanent dismiss bound the risk |
| D2: learning signal = History inline repair (`history.update_text` `edited_from`), not a live accessibility observer on the edited field (upstream `TypingService.swift:525-532` kAXValueChangedNotification) | no AT-SPI text-field observation on Linux yet (roadmap keeps it later); v1 scope: no re-dictation, no external editors |
| D3: suggestions surface as a persistent Settings list ("Suggested words"), not a typing-time 5 s overlay (upstream `AutomaticDictionaryCorrectionOverlay.swift`) | no D2 signal at typing time; a passive list needs no interruption ⇒ none of upstream's cooldowns/session-ignores; Settings is where the dictionary lives |
| D4: dismissal is permanent, not upstream's 7-day dismissed-pair cooldown with max-3 dismissals (Tracker:236-237) | the brief mandates "never resuggested"; simpler and stricter |
| D5: counts persist with no 7-day occurrence window (Tracker:234-235) and derive from the history itself, not a stored state file | the 5000-entry history cap bounds them; the store records decisions only (dismissed/accepted) |
| D6: token-level difflib over the whole edit, not upstream's anchored in-range character diff expanded to token boundaries | our edit boundary is one whole History entry (a single edit event), so anchoring is trivially satisfied |
| D7: no config toggle (upstream `automaticDictionaryLearningEnabled`, default on) | upstream's toggle gates an interruptive overlay; a passive list that only records what the user already typed needs no gate — `history.save = false` disables the signal at the source |
| D1 corollary: suggest-only, unlike the Windows port which silently auto-adds (windows-v0.0.8: "FluidVoice adds it to your custom dictionary, with a card to undo") | silent dictionary growth degrades trust (research §5) — nothing enters without an explicit Accept |

---

## 🚧 Left (see ROADMAP.md for details and upstream references)

### Near term — daily-driver polish (v0.2)
- [ ] **Rewrite/Write mode** — selection capture, edit prompts (already
      ported verbatim), dedicated hotkey.
- [x] **Hold-mode key passthrough** — DONE: keys typed during a push-to-talk
      hold reach the focused app as REAL events (the XGrabKey activation is
      released for the hold's duration; release detected via auto-repeat-proof
      query_keymap polling; passive Escape grab keeps cancel-during-hold;
      hotkey re-armed after). An XTEST ungrab→inject→re-grab replay design
      was prototyped and rejected: live Xorg 21.1 drops XTEST fakes that
      match the current key state, so replayed presses are deduped away.
      Remaining divergence (deliberate): typed keys do not end the dictation
      (upstream clean-tap interrupts), and the held hotkey's auto-repeats
      reach the app.
- [ ] Per-model language selection (one global language today).

### Wayland parity (v0.3)
- [ ] Insertion via ydotool/wtype; wl-clipboard restore; DE-shortcut /
      evdev hotkey paths.

### Models (v0.4)
- [x] **Parakeet TDT v2/v3 via ONNX** — DONE: curated sherpa-onnx tarball
c      catalog (v2 English / v3 multilingual, int8) with sha256-verified
      multi-file download (tarball + per-file checksums, atomic model dir,
      streamed extraction — never extractall), pure-numpy log-mel
      featurizer + greedy TDT decode over ONNX Runtime (CUDA execution
      provider picked up automatically when the installed wheel has it);
      Settings → Models "Parakeet (ONNX)" group with download progress +
      Use, doctor resolution report, `parakeet` pip extra.
      *Divergence (deliberate): `backend = "auto"` still prefers the
      whisper family — upstream runs Parakeet as its default; Parakeet is
      explicit-selection-only here.* Default model is v2 (upstream defaults
      to v3).
- [ ] Parakeet Realtime / Nemotron 3.5 streaming (NeMo/Riva) — unlocks real
      streaming preview.
- [x] whisper.cpp GGUF auto-download + model manager — DONE: curated GGUF
      catalog with one-click streaming download (progress, atomic rename),
      name-or-path `model.whispercpp_model`, "Use" hot-swaps the backend,
      doctor resolution report.

### Later
- [x] Command mode **v1 shipped**: dedicated `hotkey.command_key`, strict-JSON
      one-command-at-a-time agent loop over the configured AI endpoint, pill
      awaiting-confirmation state, Escape cancel + confirm timeout, per-command
      history entries. (Native tool_calls, chat persistence, multi-tool schema
      stay later.)
- [ ] GAAV + continuous-dictation formatting (needs caret text via AT-SPI).
- [ ] Slash-command/mention literal formatting + terminal autocomplete spacing.
- [x] **Insertion hardening** — DONE: paste verify-then-restore (selection
      ownership + read observation before the clipboard restore, unverified
      pastes fall back to typed insertion with a notification),
      clipboard-manager hygiene markers (CopyQ 7.1.0 live-verified; the
      GNOME-shell-extension residual and the full live evidence are recorded
      in the Done section above), terminal `ctrl+shift+v` paste key
      (`insertion.terminal_paste_key`, shared `general.terminal_apps` key),
      `insertion.verify_paste` toggle + doctor lines. The AT-SPI insertion
      fallback stays open (grouped with the AT-SPI work above).
- [x] Input-device monitoring / Bluetooth auto-switch — DONE: mic priority
      list (`recording.mic_priority`, tray + settings editor) + pactl source
      monitoring (3 s diff poll) with vanished-device auto-switch (bluez
      pattern example in README); never mid-take, auto never overridden.
      MPRIS media pause shipped earlier.
- [ ] Updater; local OpenAI-style HTTP API;
      packaging (AUR/nix/deb/pipx).

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
| Command mode (JSON protocol, agent loop, run_shell, daemon confirm/cancel/timeout) | stub-AIClient unit + integration-style daemon tests (pill overlay, Escape, history file) |
| Socket config actions (get/set-config, select-model) + apply_settings | unit (fake backend factory) + real-daemon socket integration |
| Mic monitoring (pactl poll/diff/priority matching, daemon auto-switch, tray ordering) | unit (fake pactl runner, stub recorder daemon) |
| Recorder / insertion / history / backends | stub or subprocess-mock tests |
| End-to-end speech | JFK sample through GPU transcription (pytest `-m slow`) |
| Live hardware loop | mic→GPU transcription via speaker playback; hotkey grab on X11; acoustic JFK transcription verified verbatim |
