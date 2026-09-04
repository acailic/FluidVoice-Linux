# macOS parity and beyond — idea catalog + sequencing

**Date:** 2026-09-05
**Status:** Approved (plan mode) — Phase A + Phase B in flight; C/D tracks documented for later cycles.
**Inputs:** upstream Swift sources (`~/Documents/github/FluidVoice`), docs/research/2026-09-05-fluidvoice-reviews.md (review/issue survey), docs/research/2026-09-04-product-proposals.md (P1–P8 menu), requests/streaming-finalization.md, current port state at 3576ae0.

## Context

The port (v0.5.0) matches macOS on structure: pill overlay with mode accents, tray, 6-page settings, history with confidence dots + inline repair, command mode, rewrite mode, onboarding, doctor, deb/AUR packaging. The proposals menu's small items (P1 self-healing grabs, P2 history integrity, P6 settings depth, P7 updater, P8 mouse PTT + lock) are all shipped. The strategic fork got answered from two directions overnight: **P5 command-mode v2 partially landed** (03d243f multi-tool protocol, 3576ae0 destructive-command list — remaining: conversation store, History Commands tab), and **this design picks P4 (feel: streaming preview) as the next build**, with P3 (Wayland) the recommended cycle after. Upstream's own Linux build is "coming soon" (reviews doc, insight 11) — the differentiation window is time-boxed.

The single most evidence-backed finding from the review survey (insight 1): the **live word-by-word preview overlay is upstream's #1 praised feature** — "the feature I missed most after uninstalling", ranked #1 "mostly on live preview + default-on cleanup". Upstream bug #833 names the design trap: live preview must not re-transcribe the whole buffer each tick. Windows v0.0.7 shows the pragmatic model: preview streams in the overlay, only the final transcription is inserted.

## Idea catalog

### A. Feel — make it feel like the Mac app

- **A1 Streaming live preview (Phase A, building now).** Segmented finalization per requests/streaming-finalization.md: fixed 2.0 s windows / 50% hop, incremental decode with rolling `initial_prompt`, constant per-tick decode cost (assert in tests), energy+ZCR VAD early-stop ("detect silence and finish"), final transcript stays a full-take decode. Also generalize preview beyond faster-whisper (`daemon.py` `_start_preview` currently requires `backend._model`) so whisper.cpp/Parakeet/torch get preview. Preview lag drops from ~1.2 s and O(take) cost to one window's decode per hop.
- **A2 Pill hover chips (stretch, last).** Upstream shows hover chips while recording: prompt selector, mode switcher, actions menu (reprocess last, copy last, paste last, undo AI). X11 override-redirect windows can accept pointer input without focus; riskiest visual item, ships after the pack. Windows 0.0.7 evidence: AI Prompt selector + mode selector + Paste-Last in overlay controls.
- **A3 Calm visualizer + word count (small, fold into A2 or B).** Upstream: "audio visualizer calmer… microphone noise no longer registers as movement" + word count in overlay (discussion #904). Port has fast-attack/slow-release already; noise-floor gating is the increment.

### B. Parity — features the Mac app has that we lack (each S–M, independently shippable)

- **B1 Up to 3 dictation shortcuts with per-shortcut prompt profile.** Upstream v1.5.12+ ("two configurable shortcuts — one with AI ON, one raw"); issue #834 asks multiple hotkeys→different models. Killer convenience: "button 8 = terse notes, Right_Control = polished email". Config + `hotkey.py` + settings UI.
- **B2 Paste-Last-Transcription hotkey + undo-AI / reprocess-last actions.** History stores `raw` + `ai`, so reprocess and undo-AI are cheap; upstream ships Paste Last as a shortcut and an overlay action.
- **B3 Activation mode "both"** (toggle + hold active simultaneously, disambiguated like upstream `HotkeyActivationMode`); today toggle XOR hold.
- **B4 Dictionary spoken-formatting actions:** trigger word → new line / paragraph / tab / punctuation (upstream v1.6.9); our dictionary does plain replacement only (`processing/dictionary.py`). Reviews doc confirms spoken formatting is "Gap".
- **B5 Spoken slash/mention grammar:** "slash fix", "at sign John", "tag John" (only literal `/ fix` + `@ John` squeeze ported; `processing/slash.py`).
- **B6 Stats page:** streak, time-saved (WPM-based), 7/30-day activity chart, milestones — upstream StatsView. Data already in `history.jsonl` + today stats; extend gtkui with a Stats page. Streak opt-out exists upstream (#821) — keep it dismissable.
- **B7 Spoken-send quiet-countdown** — gated on A1's VAD tail detector; follow-up inside A1's spec, not separate work.

### C. Exceed — things macOS doesn't have (documented, later cycles)

- **C1 Scriptable unix-socket API.** Upstream ships a loopback HTTP API (PR #715) for on-device agents. We beat it within the locked no-TCP scope by exposing transcribe/history/toggle routes on the existing control socket — scriptable, sandbox-friendly, no new attack surface.
- **C2 AT-SPI caret-context smart typing.** Context-aware caps/GAAV like macOS AX + insertion fallback; unblocks upstream-parity "smart capitalization" (#840 shows their version misfiring — we can do better).
- **C3 n-best pick lists.** Upstream has *none* (single-best only); blocked until a backend exposes alternates (uplift brief defers it — keep deferred).
- **C4 Per-app behavior profiles** unifying per-app prompts + insertion mode + terminal rules into one editor.
- **C5 Diarization** for file transcription (upstream shipped v1.6.8; most-reacted issue #18).

### D. Reviews-driven — answers to upstream's loudest complaints (later cycles, cheap wins)

- **D1 Idle model-unload / keep-warm policy.** Upstream's "3 GB RAM tax" fight (#548, #854, #922: 10-min-idle → 5 s first dictation). A user-visible toggle — keep-warm X minutes then unload — answers both complaints at once and differentiates on mixed Linux hardware.
- **D2 Multilingual leapfrog (personally relevant: Slovenian/Serbian).** Upstream's weakest area (#506 open, #100 closed-wontfix): fast language-switch action/hotkey (maintainer promised, never shipped), language-restricted whitelist for Whisper multilingual to kill wrong-language hallucination ("short sentences come out Russian").
- **D3 OpenAI-compatible remote STT endpoint as a backend.** LAN GPU box / vLLM / NIM serving `/v1/audio/transcriptions` (discussion #615, 14 comments). Upstream *declined* the community PR — it's a free differentiator, and "local-first" holds (nothing leaves the LAN).
- **D4 First-word capture regression guard.** Upstream's worst regression (v1.6.6 dropped opening words; fix brag: 350 ms → <100 ms). Add a trigger-latency + boundary-word regression test to the port's PTT path.
- **D5 AI refusal/derail guardrail.** Upstream pasted "I'm sorry, I can't assist with that." into a document (#925, GetVoibe). Never let a refusing/hallucinating LLM type into the user's doc — detect refusal patterns, fall back to raw transcript + notify.

### Won't do (locked scope)

Notch UI (N/A on Linux), TCP/HTTP listener (unix socket only), dual UI, mascot art, telemetry (permanent divergence — reviews insight 13 says opt-in-only upstream, we go none), changing pill geometry/mode accents, autonomous command execution, bundling closed models.

## Sequencing (approved)

1. **Phase A now** — A1 streaming preview (fully briefed, evidence-backed, no new deps). A2/A3 last inside the cycle.
2. **Phase B next** — parity pack in shippable order B2 → B1 → B3 → B4 → B5 → B6 (B2 cheapest first; B7 rides A1's VAD).
3. **Next cycle** — P3 Wayland (docs' own strategic rec; moat vs incoming upstream Linux build) while P5's remainder (conversation store, Commands tab) lands as palate-cleansers. D1/D2/D4/D5 are small enough to slot anywhere; C-track stays a menu.

## Acceptance (per phase)

Phase A done = the streaming-finalization brief's "done means": suite green (`.venv/bin/python -m pytest -q tests --ignore=tests/integration`), fake-backend decode-call count grows linearly on a synthetic long take, final transcript equals full-decode result, trailing-silence takes auto-stop at ~the configured threshold while all-silence takes keep first-PCM semantics, live smoke logs the instrumentation line, UPSTREAM-TRACKING row updated. Phase B items each = spec + code + settings UI rows + tests + STATUS/ROADMAP/UPSTREAM-TRACKING/README row updates, committed and pushed per item on `linux`.
