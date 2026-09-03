# Roadmap

Audit-verified 2026-09-01 by a 5-agent comparison against the upstream Swift
sources. Everything below is a known, classified gap — see
[BEHAVIOR-SPEC.md](BEHAVIOR-SPEC.md) for the upstream references.

## v0.2 — daily-driver polish
- [x] Live streaming preview — DONE: raw-PCM recording + rolling
      faster-whisper passes + X11 overlay window (or replaceable
      notifications); verified end-to-end with pixel-level screenshot proof.
- [x] Rewrite/Write mode — DONE: `hotkey.rewrite_key` captures the selection
      (clipboard snapshot + restore), dictates the instruction, runs it
      through the verbatim edit prompts (temperature 0.7, context block,
      follow-up history), types the result over the selection.
- [x] First-PCM timeout (2s) — DONE: live-but-silent mics stop early with a
      notification (probes the raw stream, not the finalized WAV).
- [x] Hold-mode key passthrough — DONE: keys typed during a push-to-talk
      hold reach the focused app as REAL events (the XGrabKey activation is
      released for the hold's duration — X11 gives that activation a full
      keyboard grab — with release detected by auto-repeat-proof query_keymap
      polling, a passive Escape grab keeping cancel-during-hold, and the
      hotkey re-armed after). An XTEST ungrab→inject→re-grab replay design
      was prototyped and rejected by live testing (Xorg 21.1 drops XTEST
      fakes that match the current key state). The upstream interrupt
      semantics deliberately stay out: typed keys keep the dictation running
      instead of ending the trigger (clean-tap state machine remains a
      divergence, see STATUS).
- [x] Escape cancels aborted hold recordings (not stop-and-transcribe).
- [x] Spoken-send — DONE (final-transcript variant): trailing phrase strips
      and presses enter/shift+enter/ctrl+enter after typing; "literal send
      it" escape honored. Immediate-stop countdown needs streaming VAD.
- [x] Paste-last-transcription — DONE: `fluidvoice paste-last` + socket action.
- [ ] Per-app prompt sets and user-editable prompt profiles (upstream has
      per-slot gating; we have one global toggle).
- [x] Always-copy-to-clipboard option; sub-1s zero-padding — DONE.
- [x] GAAV mode (lowercase-first / strip trailing period) — DONE.

## v0.3 — Wayland parity
- [ ] Insertion via ydotool/wtype + wlr virtual-keyboard protocol.
- [ ] Hotkey: document/bind DE shortcuts per compositor (GNOME/KDE/COSMIC);
      optional evdev listener for physical push-to-talk.
- [ ] Clipboard via wl-clipboard (wl-copy/wl-paste) with restore.

## v0.4 — model variety
- [ ] Parakeet TDT v2/v3 on GPU via NeMo / ONNX Runtime — upstream's default
      model and the highest-value Linux addition.
- [ ] Parakeet Realtime / Nemotron 3.5 streaming (NeMo/Riva) — unlocks the
      live-preview feature with real streaming cadences.
- [x] whisper.cpp GGUF auto-download — DONE: curated `ggerganov/whisper.cpp`
      ggml catalog in Settings → Models with streaming one-click download
      (progress, atomic rename), name-or-path `model.whispercpp_model`, and a
      doctor resolution report.
- [ ] Per-model language selection (whisper/cohere/nemotron stores upstream).
- [ ] Model manager: list/download in `~/.cache/fluidvoice/models` — partially
      done (faster-whisper one-click switch + GGUF downloads in Settings →
      Models); prune/freeing stays open.

## Later
- [ ] Command mode (voice → terminal agent) with the upstream tool schema and
      destructive-command confirmation list.
- [ ] GAAV mode + continuous-dictation formatting (smart caps from the text
      before the caret; needs preceding-text capture via AT-SPI).
- [ ] Slash-command/mention literal formatting (`/ fix`, `@ John Smith` in
      Slack/Discord/Teams) + terminal autocomplete spacing.
- [ ] Insertion hardening: paste-verification before clipboard restore,
      transient marks so clipboard managers ignore dictation, per-app paste
      quirks (terminals), AT-SPI insertion fallback.
- [x] Input-device monitoring / Bluetooth auto-switch — DONE: mic priority
      list (`recording.mic_priority`) + a 3 s pactl source diff poll that
      switches to the first priority match when the configured mic vanishes
      (never mid-take; auto device untouched). The MPRIS media pause half
      shipped earlier. Drag-to-reorder in the settings editor stays a
      polish item (up/down buttons for now).
- [ ] Custom-dictionary auto-learning from post-insertion corrections.
- [x] Audio-history ZIP export; local usage stats — DONE: `fluidvoice
      history --export PATH.zip` (history + retained audio; audio outside the
      audio dir refused, missing skipped), History-window Export… menu item,
      today line in the window header + `fluidvoice status` (local midnight).
- [ ] Auto-updater (or packaged releases); onboarding.
- [x] Settings UI — done as a native GTK 4 + libadwaita app
      (`fluidvoice app`; History/Settings/onboarding windows over the
      control socket; the former web page was retired with it).
- [ ] Local HTTP API (upstream exposes an OpenAI-style server on 127.0.0.1
      with /v1/transcribe, /v1/history, dictionary routes).
- [ ] Packaging: AUR, nix, pipx (deb is DONE - packaging/build-deb.sh: launcher entry, login autostart, icon, systemd unit, bundled venv).

## Non-goals
- Bundling a closed-source "Fluid Intelligence" equivalent — use any local
  OpenAI-compatible server (Ollama/LM Studio/llama.cpp) instead.
- Cohere Transcribe (CoreML-only upstream artifacts; no Linux runtime).
- macOS support (upstream owns that).
- Telemetry (upstream has opt-in/out analytics; we ship none, deliberately).
