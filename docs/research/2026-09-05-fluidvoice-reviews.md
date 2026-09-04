# FluidVoice (altic) — Online Reviews & User Feedback Research

**Date:** 2026-09-05
**Purpose:** Survey of reviews, discussions, and user feedback for FluidVoice, the macOS on-device dictation app by altic (github.com/altic-dev/FluidVoice, altic.dev/fluid), to guide priorities for **SayItErmano**, the unofficial Linux port. Focus: what users praise (parity must-haves), complain about (fix/avoid), and request (roadmap), with emphasis on feedback relevant to a Linux port. Disambiguation applied: unrelated products named "Fluid Voice" (2009 Web-2.0 group-comms tool, Android VoIP apps, speech-therapy apps) were excluded.

**Method note / source quality:** GitHub issues, discussions, and release notes were read directly via the GitHub API (primary sources). HN was queried via the Algolia API. Reddit blocks all programmatic access from this environment (curl, WebFetch, web reader, archive.org snapshots are JS-challenge shells), so Reddit content was reconstructed from search-engine snippets of the actual threads — quotes below are real but thread context is partial. Third-party reviews were fetched in full. Every claim has a URL; nothing was invented. Inference is labeled as such.

---

## Executive summary

FluidVoice (GPLv3, macOS, 11.2k GitHub stars as of 2026-09-05, ~100k downloads claimed) is the community's default answer to "free local dictation on Mac." Users praise: raw STT speed on Apple Silicon ("text landing more or less as I finished speaking"), the **live word-by-word preview overlay**, **default-on AI cleanup**, custom dictionary with **auto-learning from corrections**, and the $0/no-subscription stance. Users complain, loudly and repeatedly, about: **reliability** — audio-device-switching crashes/hangs (July–Aug 2026 was a near-continuous fire), Bluetooth/AirPods misbehavior, update regressions that drop the first words of dictation, ~3–3.5 GB models pinned in memory, an erratic closed-source enhancement model (Fluid Intelligence/Fluid-1), clipboard overwriting, and modifier-only hotkey false triggers. Non-English/multilingual support is the weakest feature area (Parakeet has no language selection; multilingual users beg for runtime language switching — still open). **Most strategically important finding for SayItErmano:** an upstream maintainer said in July 2026 that *"a windows/linux version coming out soon that should leverage any GPU"* is on the roadmap — the port's differentiation window may be finite. The single biggest product-level lesson from upstream's history: **latency regressions (first-word capture) and reliability, not accuracy, are what make users abandon the app** — Wispr Flow stays the reviewer's pick purely because FluidVoice "remains buggy."

---

## Top actionable insights for SayItErmano

1. **Streaming partial results in the overlay are the #1 praised feature — make them the port's #1 priority.**
   Evidence: Adam Jones's 21-app comparison ranks FluidVoice #1 on macOS *"mostly on live preview + default-on cleanup, and partly on the robust paste mechanism"* (https://adamjones.me/blog/best-dictation-apps-2026/, 2026-04-15). The Windows beta's flagship v0.0.7 feature was a *"live transcription preview: dictated text now appears in the recording overlay while you speak, streaming in word by word"* (https://github.com/altic-dev/FluidVoice/releases/tag/windows-v0.0.7, 2026-08-05). GetVoibe's reviewer called the preview *"the feature I missed most after uninstalling"* (https://www.getvoibe.com/resources/fluidvoice-review/, 2026-08-07). Reddit thread literally titled "Dictation apps that type AS you talk?" (https://www.reddit.com/r/macapps/comments/1rwrgx5/). Feature request #409 "Live dictation / no buffer" (https://github.com/altic-dev/FluidVoice/issues/409).
   Why it matters: SayItErmano explicitly lacks streaming; this is upstream's most-cited UX win. Windows 0.0.7 shows the pragmatic design: preview streams in the overlay, **only the final transcription is inserted** — avoiding the per-word key-injection problem the macOS dev described in #409. Known pitfall to design around: live preview must not re-transcribe the whole buffer each tick (bug #833, https://github.com/altic-dev/FluidVoice/issues/833).

2. **Guard first-word capture and hotkey-to-audio latency like the product depends on it — because for FluidVoice it did.**
   Evidence: v1.6.6 regression *"dictation trigger key has a startup delay and drops opening/closing words"* — user: *"No problems in 1.6.5, unusable in 1.6.6"*; *"Can you send me the deck" landed as "send me the deck"* (issue #751 https://github.com/altic-dev/FluidVoice/issues/751; GetVoibe review). Fix shipped in v1.6.7: *"Reduced first-word capture latency from about 350 ms to under 100 ms"* (https://github.com/altic-dev/FluidVoice/releases/tag/v1.6.7, 2026-08-05).
   Why it matters: a dictation app that eats the first words of every utterage is instantly unusable; the port's push-to-talk path needs a regression test for trigger latency and boundary-word capture.

3. **Dictionary auto-learn from corrections is beloved — keep it, and extend it toward "Train by Voice."**
   Evidence: requested in #272 (https://github.com/altic-dev/FluidVoice/issues/272, 2026-04-12), shipped v1.6.3: *"FluidVoice can suggest Custom Dictionary replacements after you repeatedly correct dictated text"*; v1.6.2 added learning corrections *"from your voice"*; Windows 0.0.8 turned *"Learn from your edits"* on by default: *"Correct a word after a dictation and FluidVoice adds it to your custom dictionary, with a card to undo. Only distinctive words, never everyday ones."* The original scathing review (Oct 2025) listed missing custom dictionary as a dealbreaker (the recurring "80K"→"ADK" error, https://wow.pjh.is/journal/fluidvoice-dictation).
   Why it matters: SayItErmano already has dictionary+auto-learn — this confirms it's parity-critical, and the "undo card" + "only distinctive words" heuristics + pronunciation-sample training (Train by Voice, v1.6.3) are the obvious next increments.

4. **Offer an idle model-unload / keep-alive policy; don't repeat the "3 GB RAM tax" fight.**
   Evidence: issue #548 — 3.43 GB model *"stays pinned in wired memory and never unloads, freezing 8 GB Macs"* (https://github.com/altic-dev/FluidVoice/issues/548, 2026-07-07); discussion #854 — *"I might dictate a few hundred words, then nothing for the next hour… during that period… ~3GB memory"* (https://github.com/altic-dev/FluidVoice/discussions/854); user pushback: *"This is buggy behavior, please stop pretending this is a design choice."* Upstream refuses time-based unload (latency reasons, #548 maintainer comment) and is instead shrinking the model (1.4 GB beta teased in #854; Fluid-1 Mini 1.5 GB shipped on Windows 0.0.8). Related: discussion #922 — after ~10 min idle the first dictation takes ~5 s; user asks for a configurable keep-awake window (https://github.com/altic-dev/FluidVoice/discussions/922).
   Why it matters: Linux users on mixed consumer hardware are more memory/GPU-sensitive; a user-visible toggle (keep-warm X minutes → unload) directly answers both complaints and differentiates the port.

5. **Non-English and multilingual switching is upstream's weakest spot — the port's biggest chance to beat upstream (and it's personally relevant: Slovenian/Serbian).**
   Evidence: #506 (open, 3 reactions) — Arabic/English user: transcription *"prone to phonetic hallucinations if the spoken language doesn't match"*; Dutch/English user asks to *"switch language… in one of the action buttons"*; maintainer: *"Actions-> switch lang… i'll find a way to hook it up soon"* — still not shipped as of 2026-08-31 (https://github.com/altic-dev/FluidVoice/issues/506). #100 — English+German user *"for shorter sentences I often get a Russian result"*; closed because *"Parakeet doesn't allow language selection"* (https://github.com/altic-dev/FluidVoice/issues/100). Discussion #905 — Russian users requesting GigaAM v3 (https://github.com/altic-dev/FluidVoice/discussions/905). Competitor contrast: Superwhisper is recommended partly for *"automatic language switching"* (https://www.reddit.com/r/macapps/comments/1ok56lk/). Language coverage: Parakeet Flash/TDT v2 = English-only; TDT v3 = 25 langs; Cohere = 14; Whisper = up to 99 (https://altic.dev/fluid, https://explainx.ai/blog/fluidvoice-macos-open-source-dictation-fluid-intelligence-2026).
   Why it matters: per-model language selection already exists in SayItErmano; adding (a) a fast language-switch action/hotkey, (b) a language-restricted whitelist for Whisper multilingual to prevent wrong-language hallucination, and (c) auto-detect would leapfrog upstream for exactly the bilingual users upstream is failing.

6. **Preserve the user's clipboard on paste, and hide temporary pasteboard writes from clipboard managers.**
   Evidence: open bug #929 — *"Dictated text overwrites the system clipboard, losing previously copied content"* (https://github.com/altic-dev/FluidVoice/issues/929, 2026-09-01); #260 — *"Copy to Clipboard" toggle does not prevent clipboard writes* (https://github.com/altic-dev/FluidVoice/issues/260); v1.6.7 fix: *"Prevented temporary dictation pasteboard writes from appearing in supported clipboard managers' history"* (release notes).
   Why it matters: insertion via clipboard is the port's likely paste strategy on X11/Wayland; users notice destroyed clipboards immediately. Plan restore-on-paste or a selection-paste (middle-click) path.

7. **Get paste/insertion right in terminals and quirky apps — "robust paste mechanism" is a stated competitive advantage.**
   Evidence: Adam Jones: FluidVoice wins *"partly on the robust paste mechanism"* (https://adamjones.me/blog/best-dictation-apps-2026/); v1.6.5: *"Pasting now works more reliably in Ghostty, tmux, and other terminal-based apps"*; open bug #479 — dictation into Claude Code under cmux inserts only "a"; #802 — *"Consecutive dictations into Ghostty stall for seconds."*
   Why it matters: the dictation-into-AI-terminal (Claude Code etc.) use case is now mainstream (see João Queirós's "prompt-capture layer" framing, https://www.ai.joaoqueiros.com/blog/fluidvoice-free-local-dictation-ai-workflows). Linux target users live in terminals; test insertion in tmux, kitty, Ghostty, VS Code, browsers, and Electron apps, with a clipboard-fallback mode (upstream added *"onboarding and clipboard-only dictation without Accessibility"*, PR #629).

8. **Debounce and filter modifier-only / push-to-talk hotkeys — false triggers were a recurring bug family.**
   Evidence: v1.6.8 fix: *"Fixed modifier-only dictation shortcuts incorrectly firing after unrelated Shift-key combinations"*; open #688 — *"Left Option modifier-only hotkey falsely triggers recording on Shift+Enter"* (https://github.com/altic-dev/FluidVoice/issues/688); #675, #609 same family; #327 requested Shift-modified shortcuts (https://github.com/altic-dev/FluidVoice/issues/327). Also shipped: activation modes Toggle / Hold / Automatic (v1.5.14) and a dedicated cancel-recording shortcut defaulting to Escape (v1.5.12).
   Why it matters: the port's global-hotkey + mouse push-to-talk must not fire on unrelated modifier sequences; offer all three activation modes and an Escape-cancel.

9. **AI text-rewriting/cleanup is what turns "raw STT" into a product — but make it fast, local-first, optional per-shortcut, and never let it refuse.**
   Evidence: the original critical review: *"it can't tidy up your dictations unless you enable cloud-based processing"* — filler words survive, no paragraphs/bullets (https://wow.pjh.is/journal/fluidvoice-dictation, Oct 2025; local tidy-up later shipped). Default-on cleanup is half of why Adam Jones ranks it #1. Counter-evidence: #925 — *"Fluid Intelligence is unusably slow"* (~5 s on M3 Pro, https://github.com/altic-dev/FluidVoice/issues/925, 2026-09-01, open); GetVoibe: Fluid-1 *"summarized dictation instead of cleaning it… once pasted 'I'm sorry, I can't assist with that.' into a document."* Upstream UX: two configurable shortcuts — one with AI ON (custom prompt), one raw (v1.5.12); speed controls; per-mode models; OpenAI-compatible/Ollama/LM Studio custom providers (discussions #854, #914).
   Why it matters: the port's base prompts + profiles are the right skeleton; add (a) a fast local post-processing path (small model or templated cleanup), (b) per-shortcut AI on/off, (c) guardrails so a refusing/hallucinating LLM never types into the user's document, and (d) a good default cleanup prompt — Adam Jones found upstream's default *"mediocre — a custom one is recommended."*

10. **Do audio-device-change reliability testing (PipeWire/PulseAudio) — it was upstream's single biggest bug cluster and reputation risk.**
    Evidence (July–Aug 2026): #682 hang on audio-device change; #644/#665 crashes on audio source switch; #542 deadlock on default device change; #709 hang switching preferred mic ↔ AirPods; #788 wrong mic selected after 1.6.7 update; #846 continuous AirPods disconnects; v1.6.8 shipped a saved **microphone priority list** with drag-to-reorder as the structural fix (https://github.com/altic-dev/FluidVoice/releases/tag/v1.6.8). GetVoibe reviewer hit mic bugs "3 ways" (AirPods switch froze dictation; wrong mic after update; USB mic losing pinned status).
    Why it matters: on Linux, device switching (Bluetooth headset connect/disconnect, USB) exercises PipeWire in the same ways; a mic-priority list + deterministic fallback is the proven upstream answer and is portable as a design.

11. **Treat upstream's official Linux build as an incoming competitor — differentiate now (Wayland, packaging, openness).**
    Evidence: maintainer grohith327, 2026-07-08, discussion #615: *"Right now since we are a Mac app, our backend is in Swift and the models use CoreML. **We have a windows/linux version coming out soon that should leverage any GPU**"* (https://github.com/altic-dev/FluidVoice/discussions/615). ExplainX notes the About line reads *"Windows, iOS and Linux coming soon"* (https://explainx.ai/blog/fluidvoice-macos-open-source-dictation-fluid-intelligence-2026). X teaser from @FluidVoiceApp: *"looking for beta testers… Smaller, faster, fully local… Hello Linux fans…"* (search-snippet, https://x.com/fluidvoiceapp — full text unverified). Counter-signal: João Queirós (2026-07-04, checked 07-27): *"There is no Linux version and none has been announced"* (https://www.ai.joaoqueiros.com/blog/fluidvoice-free-local-dictation-ai-workflows). Also note Windows builds ship as an unsigned installer flagged by 3/70 VirusTotal engines (GetVoibe) — packaging trust is a differentiator the port already wins via deb + AUR.
    Why it matters: first-mover advantage on Linux is real but time-boxed; Wayland support (port gap) and distro-native packaging are moats upstream will struggle with.

12. **A client/server "remote STT backend" is in demand and natural on Linux — consider an OpenAI-compatible transcription endpoint mode.**
   Evidence: discussion #615 (14 comments, most active feature discussion): user wants to host *"a voice model on linux server with a powerful GPU on my LAN, then point FluidVoice at it"*; another: *"Server: NVIDIA DGX Spark on my LAN, serving Whisper Large / Parakeet via an OpenAI-compatible transcription endpoint (vLLM / NIM)"*; a user forked the app to add Grok Speech over websockets (https://github.com/altic-dev/FluidVoice/discussions/615). Maintainer merged direction: PR #715 "Surface + document the loopback Local API for on-device agents" (https://github.com/altic-dev/FluidVoice/pull/715). Verified 2026-09-05: the lead maintainer **declined** the community's opt-in OpenAI-compatible engine PR ("not interested… to avoid confusion") in favor of a native "Fluid Link" protocol — i.e., upstream will NOT ship the standard endpoint, making it a free differentiator for the port.
   Why it matters: SayItErmano could accept an OpenAI-compatible `/v1/audio/transcriptions` URL as its "model" — instantly supporting LAN GPU boxes, vLLM, and even cloud — while staying "local-first" (nothing leaves the network).

13. **Trust details: make analytics opt-in (not on-by-default) and keep every model open.**
    Evidence: GetVoibe: *"analytics were enabled by default despite 'zero data leaves your Mac' marketing"*; discussion #942: *"if it is free, you are the product… analytics are on by default, and Fluid1 model is closed source"* — maintainer reply: *"We don't make money and want to commoditize basic dictation"* (https://github.com/altic-dev/FluidVoice/discussions/942). ExplainX: Fluid Intelligence is *"not shipped as open source… may bother GPL purists."*
    Why it matters: Linux audiences are the most privacy- and license-sensitive users anywhere; opt-in telemetry and fully-open models are cheap wins against both upstream and cloud competitors.

14. **Overlay details users actually notice: instant appearance, calm visualizer, size options, and inline controls.**
    Evidence: v1.6.6 *"Recording overlays now appear faster when dictation starts"*; Windows 0.0.7 — overlay size setting Medium (full panel with controls + live preview) vs Pill (compact waveform), plus overlay controls: AI Prompt selector, mode selector, Actions menu (Paste Last Transcription); *"Made the audio visualizer calmer… microphone noise no longer registers as movement"*; discussion #904 asks for word count in the overlay (https://github.com/altic-dev/FluidVoice/discussions/904).
    Why it matters: validates the port's pill UI and specifies the upgrade path (two sizes, actions menu, quiet visualizer).

15. **Pricing expectation on Linux: $0 / FOSS is table stakes — position as "free forever," never freemium.**
    Evidence: repo tagline *"Free forever, open source, and 100% on-device"* (HN comment quoting it, https://news.ycombinator.com/item?id=49421577); GetVoibe scored Pricing 10/10; Reddit warns about "free" competitors that count down to paid (Spokenly) or cap words (Aqua Voice 1,000 words/mo) (https://www.reddit.com/r/macapps/comments/1ok56lk/); community picks for free+local are exactly FluidVoice and Handy (https://www.reddit.com/r/macapps/comments/1tu5hma/).
    Why it matters: any paid tier in the port would break the category's core expectation; the differentiators must be openness, reliability, and platform fit.

---

## Detailed findings by source

### Hacker News (via Algolia API)
- Only one FluidVoice story exists: "FluidVoice - Open source voice-to-text dictation app for macOS with local AI" (2026-06-30) — **2 points, 1 comment**, and the sole comment is the maintainer of a competing Swift library self-promoting. https://hn.algolia.com/api/v1/items/48739409 / https://news.ycombinator.com/item?id=48739409
- One organic mention in the thread of "Agent Is Not the Model" (2026-08-24): karmakaze quotes the tagline *"FluidVoice turns rough, rambling speech into polished, ready-to-send text in any app. Free forever, open source, and 100% on-device"*; reply from fragmede: *"The difference between being a writer and a orator in this day and age, seems to be a bit muddy."* https://news.ycombinator.com/item?id=49421577
- A comment thread about "SnippAI" (screenshot→voice→terminal tool) says it *"uses FluidVoice to drop directly into a voice-to-text input as soon as you've taken the screenshot"* — FluidVoice as embedded infra. https://hn.algolia.com/api/v1/search?query=FluidVoice
- **Conclusion: HN is a dead channel for FluidVoice feedback. The primary sources are GitHub and Reddit.**

### Reddit (via search snippets; full threads blocked from this environment)
- **"I built FLUID – a fully free insanely fast local AI dictation app"** (r/macapps, ~Dec 2025, 352 upvotes, 226 comments, u/joller): marketed as "Whisper Flow alternative," ~6 MB app / ~100 MB RAM as original selling points. Criticism surfaced in comments: *"I notice the program puts question marks pretty accurately, but I couldn't get it to put exclamation marks"*; *"Raw dictation is often hard to use directly because it's messy."* https://www.reddit.com/r/macapps/comments/1nmlkq3/
- **"I promised to make FluidVoice, the best free open source local dictation app"** (r/macapps, follow-up ~Feb 2026): dev credits the community — *"This app literally wouldn't exist without your feedback, bug reports, and encouragement"*; commenters contrast it with MacWhisper ("lacking" for live dictation). Announced Command Mode, Rewrite, History. https://www.reddit.com/r/macapps/comments/1paekae/
- **"[OS] FluidVoice is back with a bang!"** (r/macapps, ~Jul 2026): Fluid-1 announcement — *"trained on 100,000+ synthetic real-world dictation examples that runs after Parakeet for enhancement"*; *"3 GB of local storage. I'm also working on Fluid-1 Mini, an even smaller model at around 1 GB."* https://www.reddit.com/r/macapps/comments/1ucezv2/
- **"Best FOSS macOS Dictation"**: *"I use FluidVoice which is free and open source. It works very well for me."* https://www.reddit.com/r/macapps/comments/1qdxr7m/
- **"Which of the hundred of speech to text apps is free, local"**: community consensus *"FluidVoice and Handy are the cleanest free local picks"*; FluidVoice recommended for its *"well-working edit mode."* https://www.reddit.com/r/macapps/comments/1tu5hma/
- **"Dictation apps that type AS you talk?"**: *"If local is a hard requirement, FluidVoice or built-in Apple dictation are your best options."* https://www.reddit.com/r/macapps/comments/1rwrgx5/
- **"Choosing the Right AI Dictation App"**: Superwhisper recommended for *"automatic language switching"*; warning that some "free" apps (Spokenly, Aqua Voice) are actually capped/freemium. https://www.reddit.com/r/macapps/comments/1ok56lk/
- **"Comparison of Dictation Apps"** (fiction-writing user, 54 comments): FluidVoice listed under LOCAL PROCESSING; author personally uses TypeWhisper. https://www.reddit.com/r/macapps/comments/1u4zho1/
- **r/AIToolsTipsNews crosspost** of the GetVoibe 3-week review (7/10). https://www.reddit.com/r/AIToolsTipsNews/comments/1vio658/
- **r/DigitalEscapeTools**: "FluidVoice: free, open source alternative to Wispr Flow for macOS — hold a hotkey, talk, it transcribes." https://www.reddit.com/r/DigitalEscapeTools/comments/1vkjt66/
- Related r/LocalLLaMA threads (model-level, not app-level): "What local voice to text model beats NVIDIA Parakeet v3 right now?" (wants *"higher accuracy, better punctuation and capitalization without heavy post processing"* and stronger multilingual) https://www.reddit.com/r/LocalLLaMA/comments/1sux63d/; "30 Days Testing Parakeet v3 vs Whisper" (Parakeet great for long/batch, *"as fast as cloud"*) https://www.reddit.com/r/LocalLLaMA/comments/1nf10ye/

### GitHub — altic-dev/FluidVoice (primary source; 11,248 stars, 790 forks, 89 open issues, GPL-3.0, created 2025-09-21)
**Most-reacted issues (all-time):**
- #92 Homebrew/cask distribution — 10 reactions (shipped) https://github.com/altic-dev/FluidVoice/issues/92
- #18 Speaker diarization — 10 reactions (shipped v1.6.8) https://github.com/altic-dev/FluidVoice/issues/18
- #159 Fatal SIGTRAP crash during streaming transcription — 5 https://github.com/altic-dev/FluidVoice/issues/159
- #331 Use ~/.config for all configs — 5 (open) https://github.com/altic-dev/FluidVoice/issues/331
- #457 AI Enhancement cutting off parts of prompt — 5 https://github.com/altic-dev/FluidVoice/issues/457
- #92 aside, see also #273 CSV dictionary import (3, shipped as JSON import/export v1.6.1), #506 multilingual selection (3, open), #100 language selection (3, closed: "Parakeet doesn't allow language selection")

**Bug clusters (chronological):**
- *Stability/crashes* (Dec 2025): #29 "App Stability - Feedback & Appreciation" — *"FV is exceptional and game-changing… Exactly because it's so good, I want to use it for everything"* but frequent crashes; *"longer talking sessions tend to crash… no way to recover anything from the session."* Dev engaged directly. https://github.com/altic-dev/FluidVoice/issues/29
- *Intel/macOS 14 problems* (#7, #16, #42, #62, #397): Intel is second-class (Whisper/Apple Speech fallback only).
- *Update regressions* (recurring): #751 (1.6.6 first-word drops — quotes above), #680 "recent update stopped it working", #725 "spinning beachball", #754 "1.6.6 not working at all". Users rely on the "Get previous Builds" rollback (GetVoibe).
- *Audio device switching* (Jul 2026, biggest cluster): #682, #644, #665, #624, #542, #709, #788 — see insight 10.
- *Bluetooth*: #593 degraded AirPods accuracy, #749 headset mode churn, #846 AirPods 3 disconnects, #50 mic stays open after dictation.
- *Memory*: #548 (3.4 GB wired pinned; maintainer: not unloading by design — latency; user: *"please stop pretending this is a design choice"*).
- *Hotkeys*: #688/#675/#609 modifier-only false triggers (fixed 1.6.8); #909 Return key opens dictation on macOS 26.5 (open, help wanted).
- *Clipboard*: #929 (open, 2026-09-01) dictation overwrites system clipboard; #260 copy toggle ignored writes.
- *Insertion*: #479 Claude Code/cmux inserts only "a" (open); #802 Ghostty stalls; #213 pastes from clipboard instead of dictation.
- *Enhancement quality*: #167 "AI responds to the sentence instead of improving it"; #457 prompt truncation; #925 "Fluid Intelligence is unusably slow" (open, 2026-09-01: ~5 s per dictation on M3 Pro; works instantly with enhancement off).
- *Quirks*: #840 smart capitalization always capitalizes first word; #762 "Thank you" artifact in transcripts; #910 saying "write all of this down into a markdown file" makes the model paste the entire system prompt; #825 removes 2 chars at intervals and appends them reversed.

**Feature-request themes (issues + discussions):** live dictation (#409, moved to discussions); remote STT backend (#547, discussion #615 — 14 comments; maintainer hints Linux version and easier self-hosted transcribe server); memory unload toggle (#854, 18 comments); keep-engine-warm setting (#922); true custom vocabulary beyond replacements (#916); CSV/JSON dictionary import (#273, shipped); multiple hotkeys→different models (#834); Fn key as hotkey + Esc cancel (#12, shipped as configurable cancel v1.5.12); mic selection persistence (#136, shipped 1.6.8 as priority list); disable "microphone changed" popup (#839); duck media volume instead of pause (#459/PR, and #908 "Mute sounds instead of Pause"); stats streak opt-out (#821); word count in overlay (#904); managed configuration (#892); machine sync (#881); MCP for agents (#927); medical ASR (#924); translated captions (#897); Russian GigaAM v3 (#905).

**Trust/business:** discussion #942 "How does FluidVoice make money?" — maintainer (2026-09-04): *"We don't make money and want to commoditize basic dictation. We don't do this full time… Analytics is to make us understand if people are using the app."* https://github.com/altic-dev/FluidVoice/discussions/942

### Product Hunt
No Product Hunt launch page for FluidVoice was found (searched "Product Hunt FluidVoice altic"; only generic AI-dictation category pages surfaced). **Category: none found.** If it launched there, it left no discoverable footprint.

### Mac App Store
Not distributed on the Mac App Store — distribution is direct download + `brew install --cask fluidvoice` (https://altic.dev/fluid, ExplainX). No MAS reviews exist to survey.

### Press / blogs / video
- **wow.pjh.is — "FluidVoice dictation runs locally, but I don't recommend it"** (2025-10-16, updated 2026-07-09): praises — *"It is faster than Wispr Flow, and works offline. Accuracy is similar… It's free… You don't have to trust a third party."* Original dealbreakers: cloud-only tidy-up (fillers survive, no paragraphs/bullets), no custom dictionary, onboarding bugs; July 2026 update: local tidy-up shipped, *"the app remains buggy enough that Wispr Flow remains, on balance, the best option."* https://wow.pjh.is/journal/fluidvoice-dictation
- **GetVoibe 3-week review, 7/10** (2026-08-07, updated 08-28; competitor-owned, weigh accordingly): Pricing 10/10, Features 8/10, Accuracy 8/10, Privacy 7/10, **Reliability 5/10**; live preview *"the feature I missed most"*; mic bugs "3 ways"; Edit Mode never worked; <1 s utterances silently dropped; Fluid-1 erratic (summarized, refused: *"I'm sorry, I can't assist with that."* pasted into a doc); Windows installer unsigned/flagged; verdict: *"Yes — as a free experiment on the right hardware. Not yet — as infrastructure you depend on."* and *"Free software isn't free if it costs you a workday."* https://www.getvoibe.com/resources/fluidvoice-review/
- **Adam Jones — 21-app comparison** (2026-04-15): FluidVoice **#1 on macOS** — *"FluidVoice wins, mostly on live preview + default-on cleanup, and partly on the robust paste mechanism"*; rough edges all filed upstream (#276 <1 s utterances dropped, #277/#280 cleanup prompt appends rather than templates, default prompt mediocre); on Windows/Linux *"Handy"* (MIT, 19.8k stars) is best, and its weaknesses are exactly FluidVoice's strengths (no live preview; cleanup off by default); model guidance: Parakeet v2 best for English, Cohere most accurate for non-English. https://adamjones.me/blog/best-dictation-apps-2026/
- **ExplainX** (2026-06-29, upd. 08-20): model table (Nemotron 3.5 ~40 langs/670 MB; Parakeet Flash 250 MB EN; TDT v3 25 langs; Cohere 14 langs/1.4 GB; Whisper 99 langs); Fluid Intelligence closed-source critique; analytics default-on; "Windows, iOS and Linux coming soon." https://explainx.ai/blog/fluidvoice-macos-open-source-dictation-fluid-intelligence-2026
- **João Queirós** (2026-07-04, checked 07-27): real-time preview = immediate favorite; frames it as *"not a replacement keyboard. It is a prompt-capture layer"* for Claude Code/Codex workflows; warns model download *"can look stuck around a low percentage"*; *"There is no Linux version and none has been announced."* https://www.ai.joaoqueiros.com/blog/fluidvoice-free-local-dictation-ai-workflows
- **macaiapps.com roundup (2026)**: ranks FluidVoice #9 overall; pros: speed ("<100 ms using NVIDIA Parakeet"), free, Intel fallback; cons: *"Open source means less polish,"* community-only support, *"Fewer advanced features."* (Affiliate-linked rivals fill the top slots.) https://www.macaiapps.com/blog/best-dictation-apps-for-macos/
- **YouTube**: "Open-Source Dictation Is Here… Goodbye Subscriptions" (174 comments; dev comment: "Windows is almost ready — FluidIntelligence is 2x faster in the next update — smaller Fluid model coming soon ~1GB") https://www.youtube.com/watch?v=mIL4sZa8M0E; "Free, local audio dictation. Better than Wispr Flow" https://www.youtube.com/watch?v=q_BazF9CCsU; install guide https://www.youtube.com/watch?v=z7qRJO-HaF8. (Comment bodies not retrievable from this environment.)
- **X/Twitter**: @rowlsmanthorpe: *"Really recommend Fluid Voice"*; @sdhilip: *"Corrects as I speak with no API key, and handles slang better than I expected"*; @OpenAlternative: 10k-star milestone; @FluidVoiceApp beta-tester call ("Hello Linux fans…" — snippet only). https://x.com/rowlsmanthorpe/status/2082058418173448402, https://x.com/sdhilip/status/2069140867466797200, https://x.com/fluidvoiceapp

### Competitor landscape (what makes people pick or abandon FluidVoice)
- **Wispr Flow** ($12/mo, cloud): the benchmark. Reviewers keep paying because FluidVoice *"remains buggy"* (wow.pjh.is Jul 2026). Cons cited: cloud processing, ~800 MB RAM, 8–10 s startup, 2.7/5 Trustpilot (GetVoibe).
- **Superwhisper** ($8.49/mo / $249 lifetime): picked for per-app "intelligent modes," 100+ languages, auto language switching; avoided for subscription pricing.
- **Handy** (OSS, MIT, cross-platform incl. Linux): the port's real competitor on Linux. Wins on setup ease and maintainers; loses on no live preview and cleanup off by default (Adam Jones).
- **MacWhisper**: file/meeting transcription, "for live dictation, look elsewhere."
- **VoiceInk** ($39.99 once): pay-once privacy crowd.
- **Apple built-in dictation**: still preferred by some for everyday use; FluidVoice's wins over it are custom dictionaries, cleanup prompts, and app awareness (João Queirós).
- **Abandonment triggers for FluidVoice** (synthesis, labeled inference): reliability regressions (mic/audio), Fluid Intelligence latency/refusals, memory pressure on 8 GB machines, and non-English hallucinations.

---

## Upstream shipped vs port gaps (from release notes, v1.3 2025-09-29 → v1.6.9 2026-08-18, plus Windows v0.0.1–0.0.9 Jul–Aug 2026)

**Upstream shipped, mapped to SayItErmano status:**

| Upstream capability | Since | SayItErmano (v0.5.0) |
|---|---|---|
| Local Whisper + Parakeet STT | v1.2+ | Have (faster-whisper, Parakeet) |
| Global hotkey + push-to-talk; toggle/hold/auto activation modes | v1.5.12/v1.5.14 | Have (X11); Wayland missing |
| Pill overlay + full overlay variants | v1.5.13; Windows 0.0.7 size setting | Have (pill); no size/controls variants |
| Base prompts + profiles, per-app prompts | v1.5.x/1.6.x | Have |
| Per-model language selection | v1.5.15 (Nemotron auto/manual) | Have (single per model) |
| Custom dictionary + auto-learn from corrections + JSON import/export | v1.6.1/v1.6.2/v1.6.3 | Have (auto-learn); import/export unknown |
| History (speaker-aware, text/JSON export, copy raw+enhanced) | v1.5.x–1.6.8 | Have (basic) |
| Streaming/live preview overlay | Windows 0.0.7 (Aug 2026); macOS preview exists | **Gap** |
| Fluid-1 local enhancement (closed model) + per-mode custom providers (OpenAI-compatible, Ollama, LM Studio) | v1.6.0+ | **Gap** (no AI rewrite) |
| Edit/Write Mode (rewrite selected text) | v1.5.x | **Gap** |
| Command Mode (voice control + MCP, destructive-command confirm gates) | v1.5.x; PR #290/#862 | **Gap** |
| Speaker diarization + file/batch transcription (drag Voice Memos) | v1.6.8, PR #716 | **Gap** |
| Spoken punctuation/formatting (configurable trigger word, symbols, newlines) | v1.6.2/v1.6.3/v1.6.9 | **Gap** (auto-punctuation via model only) |
| Train by Voice (pronunciation samples) | v1.6.3 | **Gap** |
| Microphone priority list + onboarding picker | v1.6.8 | Unknown/likely gap |
| Multiple primary shortcuts (AI ON / raw OFF), cancel-recording shortcut | v1.5.12/v1.6.1 | Partial (single hotkey + PTT) |
| First-word capture <100 ms; Parakeet 2x; Fluid-1 2.2x | v1.6.7/v1.6.3 | Perf target to match |
| Clipboard hygiene (no clipboard-manager spam) | v1.6.7 | Gap to verify |
| /commands and @mentions formatting | v1.6.2 | Gap |
| Homebrew cask distribution | shipped (#92) | deb + AUR already done |
| Loopback Local API for on-device agents | PR #715 (2026-07) | Gap / differentiation opportunity |

**Roadmap signals from maintainers:** Windows/Linux version "coming out soon… leverage any GPU" (discussion #615, 2026-07-08); ~1.4 GB Fluid-1 variant beta (discussion #854, 2026-08-31); easier self-hosted transcription server (discussion #615); language hot-swap action (#506, promised "soon", not shipped as of 2026-08-31).

---

## Considered but rejected / not applicable

- **Notch/Dynamic Island presentation, dock-icon behavior, clamshell mode, Universal Control, AirPods-specific route handling, Apple Speech engine, CoreML/Metal/MLX specifics** — macOS-platform-specific; noted only where the *underlying* user need (e.g., mic priority after device churn) transfers to PipeWire.
- **Fluid-1 / Fluid Intelligence the model itself** — closed-source; cannot be ported. Replacement strategy: local small LLM via Ollama/LM Studio or OpenAI-compatible endpoint (upstream itself supports this and users request it, discussions #854/#914).
- **Mac App Store reviews** — app is not distributed there; nothing to survey.
- **Product Hunt** — no launch found; category explicitly empty rather than overlooked.
- **2009 "Fluid Voice" Web-2.0 CB-radio-style product, Android VoIP "Fluid Voice" apps, speech-therapy "Fluid Voice"** — disambiguated and excluded.
- **GetVoibe's sub-scores beyond reliability/latency** — source is a direct competitor; used only for concrete, checkable claims (bug descriptions, version dates) that align with GitHub issues.
- **"I built FLUID" thread's 226 comments in full** — unretrievable (Reddit blocking); only snippet-verifiable quotes used.

---

## Sources

Primary:
- https://github.com/altic-dev/FluidVoice (issues #3 #7 #10 #12 #16 #18 #20 #29 #35 #41 #42 #50 #52 #62 #75 #92 #93 #100 #103 #104 #125 #134 #159 #163 #167 #213 #227 #255 #260 #272 #273 #275 #276 #287 #290 #327 #331 #409 #457 #459 #479 #506 #542 #547 #548 #615 #644 #665 #682 #688 #694 #751 #788 #825 #833 #846 #852 #910 #925 #929; discussions #615 #854 #905 #916 #922 #927 #942; releases v1.5.12–v1.6.9, windows-v0.0.1–0.0.9)
- https://altic.dev/fluid
- HN Algolia API: items 48739409, 49421577; https://news.ycombinator.com/item?id=48739409 ; https://news.ycombinator.com/item?id=49421577

Reviews/blogs:
- https://wow.pjh.is/journal/fluidvoice-dictation (Oct 2025 / Jul 2026)
- https://www.getvoibe.com/resources/fluidvoice-review/ (Aug 2026)
- https://adamjones.me/blog/best-dictation-apps-2026/ (Apr 2026)
- https://explainx.ai/blog/fluidvoice-macos-open-source-dictation-fluid-intelligence-2026 (Jun 2026)
- https://www.ai.joaoqueiros.com/blog/fluidvoice-free-local-dictation-ai-workflows (Jul 2026)
- https://www.macaiapps.com/blog/best-dictation-apps-for-macos/ (2026)
- https://aitecharchive.com/articles/best-free-local-dictation-mac-fluid-voice-guide

Reddit (snippet-verified):
- https://www.reddit.com/r/macapps/comments/1nmlkq3/ ; /1paekae/ ; /1ucezv2/ ; /1qdxr7m/ ; /1tu5hma/ ; /1rwrgx5/ ; /1ok56lk/ ; /1u4zho1/ ; /1pkxhjj/ ; https://www.reddit.com/r/AIToolsTipsNews/comments/1vio658/ ; https://www.reddit.com/r/DigitalEscapeTools/comments/1vkjt66/ ; https://www.reddit.com/r/LocalLLaMA/comments/1sux63d/ ; /1nf10ye/

X/Twitter:
- https://x.com/fluidvoiceapp ; https://x.com/rowlsmanthorpe/status/2082058418173448402 ; https://x.com/sdhilip/status/2069140867466797200 ; https://x.com/ossalternative/status/2088265636434890990

Video:
- https://www.youtube.com/watch?v=mIL4sZa8M0E ; https://www.youtube.com/watch?v=q_BazF9CCsU ; https://www.youtube.com/watch?v=z7qRJO-HaF8
