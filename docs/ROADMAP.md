# Roadmap

Audit-verified 2026-09-01 by a 5-agent comparison against the upstream Swift
sources. Everything below is a known, classified gap — see
[BEHAVIOR-SPEC.md](BEHAVIOR-SPEC.md) for the upstream references.

## v0.2 — daily-driver polish
- [ ] Live streaming preview (rolling faster-whisper on a sliding buffer) shown
      in a small always-on-top overlay window (X11 override-redirect).
- [ ] Rewrite/Write mode: X11 selection capture (Ctrl+C snapshot via xclip,
      restore), `fluidvoice rewrite` + dedicated hotkey, edit-mode prompt with
      selected-text context (already ported verbatim).
- [ ] First-PCM timeout (2s) + capture-health watchdog — fail fast when the
      mic is live-but-silent (wrong device, Bluetooth HFP).
- [ ] Hold-mode key passthrough: stop swallowing the keyboard during
      push-to-talk; other keys interrupt the trigger instead (upstream
      clean-tap state machine).
- [ ] Escape as default cancel key (cancel, not stop-and-transcribe).
- [ ] Spoken-send: trailing phrase ("send it") auto-stop + Enter, with the
      1.5s settle countdown + voice-activity cancel.
- [ ] Paste-last-transcription hotkey.
- [ ] Per-app prompt sets and user-editable prompt profiles (upstream has
      per-slot gating; we have one global toggle).
- [ ] Always-copy-to-clipboard option; sub-1s zero-padding for whisper.cpp.

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
- [ ] whisper.cpp GGUF auto-download (handy-computer artifacts upstream uses).
- [ ] Per-model language selection (whisper/cohere/nemotron stores upstream).
- [ ] Model manager: list/download/prune in `~/.cache/fluidvoice/models`.

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
- [ ] Input-device monitoring / Bluetooth auto-switch (playerctl MPRIS media
      pause too).
- [ ] Custom-dictionary auto-learning from post-insertion corrections.
- [ ] Audio-history ZIP export; local usage stats.
- [ ] Auto-updater (or packaged releases); onboarding.
- [x] Settings UI — done as a local web page served by the daemon
      (`fluidvoice settings`, 127.0.0.1 only, CSRF/DNS-rebinding hardened).
- [ ] Local HTTP API (upstream exposes an OpenAI-style server on 127.0.0.1
      with /v1/transcribe, /v1/history, dictionary routes).
- [ ] Packaging: AUR, nix, pipx (deb is DONE - packaging/build-deb.sh: launcher entry, login autostart, icon, systemd unit, bundled venv).

## Non-goals
- Bundling a closed-source "Fluid Intelligence" equivalent — use any local
  OpenAI-compatible server (Ollama/LM Studio/llama.cpp) instead.
- Cohere Transcribe (CoreML-only upstream artifacts; no Linux runtime).
- macOS support (upstream owns that).
- Telemetry (upstream has opt-in/out analytics; we ship none, deliberately).
