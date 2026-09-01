# Roadmap

## v0.2 — daily-driver polish
- [ ] Live streaming preview (rolling faster-whisper on a sliding buffer) shown
      in a small always-on-top overlay window (GTK layer or a bar via wlr? X11
      override-redirect window).
- [ ] Rewrite/Write mode: X11 selection capture (Ctrl+C snapshot via xclip,
      restore), `fluidvoice rewrite` + dedicated hotkey, edit-mode prompt with
      selected-text context (already ported verbatim).
- [ ] Automatic activation mode (tap=toggle, hold=push-to-talk).
- [ ] Spoken-send: trailing phrase ("send it") auto-stop + Enter.
- [ ] Per-app prompt sets (app hint already captured per recording).
- [ ] History viewer command (`fluidvoice history --copy N`).

## v0.3 — Wayland parity
- [ ] Insertion via ydotool/wtype + wlr virtual-keyboard protocol.
- [ ] Hotkey: document/bind DE shortcuts per compositor (GNOME/KDE/COSMIC);
      optional evdev listener for physical push-to-talk.
- [ ] Clipboard via wl-clipboard (wl-copy/wl-paste) with restore.

## v0.4 — model variety (upstream parity)
- [ ] Parakeet TDT v2/v3 on GPU via NeMo / ONNX Runtime (NVIDIA hardware
      already supported by the model family; English-first).
- [ ] whisper.cpp GGUF models from handy-computer (same artifacts upstream uses).
- [ ] Model manager: list/download/prune in `~/.cache/fluidvoice/models`.

## Later
- [ ] Command mode (voice → terminal agent) with the upstream tool schema and
      destructive-command confirmation list.
- [ ] Custom-dictionary auto-learning from post-insertion corrections.
- [x] Settings UI — done as a local web page served by the daemon
      (`fluidvoice settings`, 127.0.0.1 only): model picker with download,
      AI config + live test, dictation toggles, history. A tray icon may
      still be added on top.
- [ ] Local HTTP API (upstream exposes an OpenAI-style server on 127.0.0.1).
- [ ] Packaging: AUR, nix, flatpak-less deb, pipx.

## Non-goals
- Bundling a closed-source "Fluid Intelligence" equivalent — use any local
  OpenAI-compatible server (Ollama/LM Studio/llama.cpp) instead.
- macOS support (upstream owns that).
