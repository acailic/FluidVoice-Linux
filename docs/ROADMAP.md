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
- [x] Per-app prompt sets — DONE: `ai.per_app_prompts` rules matched against
      the recording-start app (Settings → AI → Per-app prompts, per-rule
      editor; the frontmost-app hint was already captured).
- [ ] User-editable prompt profiles (named presets of the base prompt).
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
- [x] Slash-command/mention literal formatting (`/ fix`, `@ John Smith` in
      Slack/Discord/Teams) + terminal autocomplete spacing — DONE: literal
      squeeze ported from upstream `DictationLiteralFormatting` (runs after
      AI cleanup, `processing.slash_mention_squeeze`; literal-`@` pass is a
      port addition mirroring upstream's spoken-mention name grammar) plus
      one trailing space on typed insertions in `general.terminal_apps`
      (`insertion.terminal_autocomplete_space`) and the spoken-send terminal
      blocklist. Upstream's spoken forms (`slash fix`, `at sign John`) stay
      tracked in UPSTREAM-TRACKING.
- [x] Insertion hardening: paste-verification before clipboard restore,
      transient marks so clipboard managers ignore dictation, per-app paste
      quirks (terminals) — DONE: verify-then-restore paste (selection
      ownership + read observation; unverified pastes fall back to typed
      insertion with a notification), clipboard-manager hygiene markers
      (CopyQ 7.1.0 live-verified; the GNOME-shell-extension residual is
      documented in STATUS.md), terminal `ctrl+shift+v` paste key, both
      config keys + doctor lines. AT-SPI insertion fallback stays later.
- [x] Input-device monitoring / Bluetooth auto-switch — DONE: mic priority
      list (`recording.mic_priority`) + a 3 s pactl source diff poll that
      switches to the first priority match when the configured mic vanishes
      (never mid-take; auto device untouched). The MPRIS media pause half
      shipped earlier. Drag-to-reorder in the settings editor stays a
      polish item (up/down buttons for now).
- [x] Custom-dictionary auto-learning from post-insertion corrections
      — DONE: inline repair (`history.update_text`) stamps the pre-edit
      text as `edited_from` (first edit wins — the ASR-heard audit trail);
      `processing/dict_learn.py` diffs it against the final text
      (token-level difflib) with upstream's shape checks (≤3 words/side,
      ≤40 chars/side, ≥2 letters/side, purely alphabetic tokens, filler-
      free — `AutomaticDictionaryCorrectionTracker.swift:215-241`) and
      suggests a pair only after it appears in ≥2 entries (upstream
      `requiredOccurrences`; counts derive from the history itself, the
      5000-entry cap bounds them). Settings → Dictation gains a passive
      "Suggested words" group (below the hand-curated editor, hidden when
      empty): Accept merges through the validated `set-config` path with
      no duplicate triggers (the merged entry verifiably rewrites the old
      form), Dismiss is permanent. Decisions live in
      `~/.config/sayit-ermano/dictionary-suggestions.json` (dismissed /
      accepted pairs only — no counts, no config key: a passive list that
      records what the user already typed needs no gate;
      `history.save = false` disables the signal at the source).
      `fluidvoice doctor` prints the pending count. Divergences (case-only
      candidates, no overlay, permanent dismiss…) in STATUS.md.
- [x] Audio-history ZIP export; local usage stats — DONE: `fluidvoice
      history --export PATH.zip` (history + retained audio; audio outside the
      audio dir refused, missing skipped), History-window Export… menu item,
      today line in the window header + `fluidvoice status` (local midnight).
- [ ] Auto-updater (or packaged releases); onboarding.
- [ ] Mouse-button push-to-talk (XGrabButton + button-state polling) —
      upstream parity candidate from the 09-02 event-tap work; plus
      suppressing hotkeys while the screen is locked.
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
