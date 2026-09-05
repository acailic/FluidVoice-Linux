# How this project relates to other dictation tools

Research date: 2026-09-01. No Linux port of FluidVoice existed when this
project started — official FluidVoice is macOS-only (plus a 0.0.9 Windows
pre-release). These are the Linux-native tools in the same space:

| Tool | Engine | AI polish | Spoken punctuation | Global hotkey | Insertion | X11/Wayland |
|---|---|---|---|---|---|---|
| **SayItErmano (this, formerly FluidVoiceLinux)** | faster-whisper / whisper.cpp / torch (CUDA) | ✅ verbatim FluidVoice prompt, any OpenAI-compatible endpoint | ✅ full "literal" rule table w/ contexts | ✅ XGrabKey (toggle+hold); Wayland: DE shortcut + evdev PTT (v0.3) | typed + paste w/ restore: xdotool/xclip (X11), wtype/ydotool + wl-clipboard (Wayland, v0.3) | X11 + Wayland (v0.3) |
| [Handy](https://github.com/cjpais/handy) | whisper.cpp | ➖ | ➖ | ✅ | paste | both (Tauri) |
| [Vocalinux](https://github.com/jatinkrmalik/vocalinux) | whisper.cpp/VOSK + Silero VAD | ➖ | ➖ | ✅ | xdotool/ydotool | both |
| [nerd-dictation](https://github.com/ideasman42/nerd-dictation) | VOSK | ➖ | ➖ | ✅ (its own) | xdotool | X11 (community Wayland) |
| [VOXD](https://github.com/jakovius/voxd) | whisper | ➖ | ➖ | ✅ | xdotool | X11 |
| [OpenWhispr](https://openwhispr.com/) | Whisper / Parakeet | ✅ | ➖ | ✅ | yes | both (Electron) |
| FluidVoice (macOS, upstream) | Parakeet/Nemotron/Cohere/Whisper/Apple | ✅ local Fluid Intelligence + cloud | ✅ (source of the rule table) | ✅ | AX/keystroke/paste | N/A |

**Why this port exists even though Handy/Vocalinux are good tools:** none of
them implements FluidVoice's differentiating behavior — the dictation-cleanup
prompt pipeline, the "literal" spoken-punctuation engine with context rules,
and per-app behavior. This project ports *that*, keeping the pipeline local
and hackable, and stays GPLv3-compatible with upstream (verbatim prompts + SFX
copied under the same license).

If you just want "press key → text appears" with minimal setup, Handy is a
fine choice. If you want FluidVoice's polished-output behavior on Linux,
that's this project's niche.
