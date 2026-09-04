# UI/HCI Research Foundations for SayItErmano

**Scope note.** SayItErmano is a GNOME/GTK4 voice-dictation app (Linux fork of macOS FluidVoice): a global hotkey starts recording; a floating overlay "pill" near the cursor shows recording state, a live waveform, mode accents (dictate/rewrite), a command panel, and a send/success badge; Whisper transcribes, an optional LLM rewrites, and text is inserted at the cursor. Supporting surfaces are a history window, settings, onboarding, and a tray icon. This document collects peer-reviewed HCI and perceptual-psychology findings that bear on how that overlay should behave — latency and turn-taking, perceived waiting, recording feedback, error correction, trust display, motion, delight, and accessibility — each mapped to a concrete design implication for the pill. Every citation below was verified against a fetched or search-confirmed source page (ACM DL, PNAS, SAGE, PLOS, IEEE, W3C, arXiv, publisher pages). Items that could not be verified are explicitly marked as such or omitted.

Verification date: 2026-09-04.

---

## 1. Turn-taking and latency: the ~200 ms conversational clock

**Finding.** Across 10 languages on 5 continents, the median gap between one speaker ending and the next beginning is ~200 ms (mode near 0 ms) — silence beyond a fraction of a second is socially informative. Stivers et al., 2009 — "Universals and cultural variation in turn-taking in conversation", *PNAS* 106(26):10587–10592. https://www.pnas.org/doi/10.1073/pnas.0903616106 (also https://pubmed.ncbi.nlm.nih.gov/19553212/)

> **Design implication for SayItErmano:** The pill should flip from "idle" to "recording" with no perceptible delay (<200 ms) after hotkey press, so the app feels like a conversational partner rather than a tool that makes you wait to speak. Any pre-roll (device wake, pipeline init) must be hidden behind an instant visual state change, never a real delay.

**Finding.** Turn gaps are shorter than the time needed to plan speech, so listeners predict turn endings and prepare responses in parallel — anticipation, not reaction, is the human model. Levinson & Torreira, 2015 — "Timing in turn-taking and its implications for processing models of language", *Frontiers in Psychology* 6:731. https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.00731/full

> **Design implication for SayItErmano:** Show predictive states during the pipeline: while the user is still speaking, the pill can already display "listening → will transcribe" affordances (e.g., waveform + pulsing edge) so the user perceives the system working ahead of them, not starting after they stop.

**Finding.** The classic HCI response-time thresholds: ~2 s is the limit for conversational ("cognitively continuous") interaction, 4 s the ceiling for many tasks, 15 s the absolute limit; feedback requirements change at each band. Miller, R. B., 1968 — "Response time in man-computer conversational transactions", *Proc. AFIPS Fall Joint Computer Conference* 33:267–277. https://dl.acm.org/doi/10.1145/1476589.1476628

**Finding.** IBM's performance study found large productivity gains when interactive responses stay under ~1 s (often quoted as the "Doherty threshold" ≈ 0.4 s); above ~2 s, users' work degrades into segmented "computer time / think time". Doherty & Thadhani, 1982 — "The Economic Value of Rapid Response Time", IBM technical report GE20-0752-0 (technical report, not peer-reviewed; scanned copy verified). https://www.scribd.com/document/657635710/IBM-The-Economic-Value-of-Rapid-Response-Time

**Finding.** Secondary synthesis (anchored to Miller 1968 and Card et al. 1991): 0.1 s = feels instant; 1 s = flow kept but not "instant"; 10 s = attention lost without progress feedback. Nielsen, 1993 — "Response times: the 3 important limits" (excerpt from *Usability Engineering*, ch. 5; authoritative practitioner source). https://www.nngroup.com/articles/response-times-3-important-limits/

> **Design implication for SayItErmano:** Budget the pill's own latency in these bands: state change < 0.1 s (instant accent + waveform start); insertion of final text < 1 s from transcription availability; any LLM rewrite exceeding ~1 s must show streamed or animated progress, and anything past ~4 s needs an explicit "still rewriting" cue (see findings below).

**Finding.** In a 478-participant experiment on conversational-system delays, users rated waiting more negatively once delays exceeded ~8 s, systematically underestimated elapsed time, and judged conversations less natural as delay grew. Abbas, Gadiraju, Khan & Markopoulos, 2022 — "Understanding User Perceptions of Response Delays in Crowd-Powered Conversational Systems", *PACM HCI* 6(CSCW2), Art. 392. https://dl.acm.org/doi/10.1145/3555765

**Finding.** With LLM-powered agents, latency above ~4 s degraded experience quality, but users actually *preferred short delays over zero delay* and perceived response time as shorter when the agent emitted natural "fillers" (gestures/verbal cues) during processing. Maslych et al., 2025 — "Mitigating Response Delays in Free-Form Conversations with LLM-powered Intelligent Virtual Agents", *CUI '25* (ACM), Art. 49; preprint. https://arxiv.org/abs/2507.22352 (DOI: 10.1145/3719160.3736636)

**Finding.** Rich typing indicators (showing the other party actively typing) increased perceived co-presence in messaging. Iftikhar, Ma & Huang, 2023 — "'Together but not together': Evaluating Typing Indicators for Interaction-Rich Communication", *CHI '23*. https://dl.acm.org/doi/10.1145/3544548.3581248 (PDF: https://jeffhuang.com/papers/LiveTyping_CHI23.pdf)

> **Design implication for SayItErmano:** During the Whisper/LLM stages, never show a static pill. Animate a working state (indeterminate shimmer, streaming word ghosts, or a "rewriting…" micro-label) from the moment recording stops; a small working animation beats both a frozen pill and instant-looking silence. Stream partial rewrite text into the pill as it arrives (progressive rendering) rather than swapping the whole string in at the end.

---

## 2. Perceived duration and waiting: fill time, show structure, accelerate

**Finding.** The foundational service-psychology propositions: occupied time feels shorter than unoccupied time; people want to get started; unexplained waits feel longer; anxiety makes waits feel longer. Maister, D. H., 1985 — "The Psychology of Waiting Lines", in Czepiel, Solomon & Surprenant (eds.), *The Service Encounter: Managing Employee/Customer Interaction in Service Businesses*, pp. 113–123, Lexington Books (book chapter). http://www.dzcowan.com/Tech%20Attachments/HS%206000/PsycholgyofWaitingLines751.pdf (citation verified: https://www.scirp.org/reference/referencespapers?referenceid=395802)

**Finding.** The classic queueing-psychology prescription: *entertain* (occupy), *enlighten* (explain), *engage* (involve) during waits. Katz, Larson & Larson, 1991 — "Prescription for the Waiting-in-Line Blues: Entertain, Enlighten, and Engage", *Sloan Management Review* 32(2):44–53. (Full text: https://www.researchgate.net/publication/304582002_Prescription_for_the_Waiting_in_Line_Blues_Entertain_Enlighten_Engage)

> **Design implication for SayItErmano:** Treat the pill's post-recording processing as a "wait line": occupy it (waveform continues into a gentle processing animation), explain it (stage label: "transcribing → rewriting"), engage it (let the user pre-aim the command panel or read the raw transcript while the rewrite streams). Give stage names, not just a spinner.

**Finding.** Progress bars that *look* faster change felt duration even at identical real duration: every bar ran 5.5 s, yet pausing/reversing bars felt longest. Harrison, Amento, Kuznetsov & Bell, 2007 — "Rethinking the progress bar", *CHI '07*. https://www.semanticscholar.org/paper/8dff60b3a929b85d096ba10008c29f34b273f07c

**Finding.** Follow-up experiment: bars with *accelerating* fill and moving visual embellishments (ribbed texture, glow) were perceived as fastest; decelerating or pausing bars felt slowest. Harrison, Yeo & Hudson, 2010 — "Faster progress bars: manipulating perceived duration with visual augmentations", *CHI '10*. https://dl.acm.org/doi/10.1145/1753326.1753556 (project: https://www.chrisharrison.net/index.php/Research/ProgressBars2)

**Finding.** With speed and distance held constant, progress displays with more, smaller steps (e.g., throbbers with fine granularity) produced time *underestimation*; fewer coarse steps dilated perceived time — perceived duration follows stimulus structure, not actual speed. Ziat, Saoud, Prychitko, Servos & Grondin, 2022 — "Malleability of time through progress bars and throbbers", *Scientific Reports* 12:10400. https://pmc.ncbi.nlm.nih.gov/articles/PMC9213475/

> **Design implication for SayItErmano:** Where total work is known (e.g., chunked Whisper decoding), render progress as an accelerating fill with fine-grained steps and a subtle moving texture rather than one big sweep; never let the pill's progress visibly stall or reverse mid-operation.

**Finding.** Loading pages with skeleton screens scored higher on perceived speed and ease of navigation than spinners (though users *noticed* the loading more). Mejtoft, Långström & Söderström, 2018 — "The effect of skeleton screens: Users' perception of speed and ease of navigation", *ECCE '18*. https://dl.acm.org/doi/10.1145/3232078.3232086

> **Design implication for SayItErmano:** When the rewrite lands, show a skeleton/ghost of the incoming text (or preserve the raw transcript in place with the polished version fading in over it) instead of a blank pill plus spinner — structure-at-the-end reads as faster and is easier to scan in the history window too.

*Note:* The prompt's hint "operational vs reactive wait / 'Myersummers'" could not be mapped to any verified paper; the verifiable core of this literature is Maister (1985), Katz et al. (1991), and the progress-bar studies above. That framing was dropped rather than fabricated.

---

## 3. Recording feedback: making "the mic is live" perceptible and trustworthy

**Finding.** Making a microphone's active state *perceptibly* tied to its operation (an intentional, physically grounded assurance signal rather than an abstract setting) improved user trust in always-on microphones. Do, Arora, Mirzazadeh, Moon, Xu, Zhang, Abowd & Das, 2023 — "Powering for Privacy: Improving User Trust in Smart Speaker Microphones with Intentional Powering and Perceptible Assurance", *USENIX Security '23*. https://www.usenix.org/conference/usenixsecurity23/presentation/do (PDF: https://www.usenix.org/system/files/usenixsecurity23-do.pdf)

**Finding.** Users often *misinterpret* ambient light-ring feedback on smart speakers: interpretation accuracy was imperfect and device-dependent (Amazon Echo users identified a higher proportion of light behaviors than Google Home users), so feedback vocabulary must be learnable and unambiguous. Kunchay, Sarrafzadeh, Rafin, Clark, Alshebli, Abdullah et al., 2021 — "Assessing Effectiveness and Interpretability of Light Behaviors in Smart Speakers", *ICMI '21*. https://dl.acm.org/doi/fullHtml/10.1145/3469595.3469610 (PDF: https://saeedabdullah.com/files/pubs/2021-light-smart-speakers.pdf)

**Finding.** Eye-tracking research on Android's camera/microphone privacy indicators examines whether users visually attend to these alerts at all — indicators compete with the user's primary task for attention. *Venue partially verified:* Guerra & Milanese, 2024 — "Visual Attention and Privacy Indicators in Android: Insights from Eye Tracking" (conference proceedings, SciTePress; exact proceedings details not fully confirmed in this pass). https://nchr.elsevierpure.com/en/publications/visual-attention-and-privacy-indicators-in-android-insights-from- — treat as directional support only.

**Gap, stated honestly:** no peer-reviewed study specifically measuring the effect of a *live waveform* on dictation confidence/speech behavior was found in this pass. The nearest verified anchors are the perceptible-assurance work (Do et al. 2023), ambient-signal interpretability (Kunchay et al. 2021), and time-perception effects of moving stimuli (Ziat et al. 2022, Section 2). Any "waveform increases user confidence" claim should be treated as a hypothesis for SayItErmano's own testing, not established fact.

> **Design implications for SayItErmano:**
> - The pill *is* the privacy indicator: give recording a high-salience state (red/orange accent + moving waveform) that is unambiguous, and a clearly distinct, calmer state for "armed but not recording". Do not use two states that differ only by hue.
> - Keep one consistent meaning per animation: pulsing = listening, lateral shimmer = transcribing, streaming text = rewriting, pop + check = inserted. Verify users actually interpret them (per Kunchay et al.) in onboarding or a tooltip on first use.
> - Because overlays compete for attention, pair color with motion for the live state (motion is detected pre-attentively), and keep the recording accent visible even when the pill is otherwise translucent.

---

## 4. Dictation error correction: design for multimodal repair and hyperarticulation

**Finding.** The canonical CHI dictation study (three commercial continuous-speech systems, initial + extended use) documented recurring correction patterns and usability problems: users get stuck in error-correction loops, and uncorrected misrecognitions silently propagate. Karat, Halverson & Karat, 1999 — "Patterns of entry and correction in large vocabulary continuous speech recognition systems", *CHI '99*. https://dl.acm.org/doi/10.1145/302979.303160

**Finding.** Multimodal error correction (combining speech with pointing/selection) is faster and more accurate than unimodal re-dictation ("respeaking") for repairing recognition errors — the classic TOCHI result. Suhm, Myers & Waibel, 2001 — "Multimodal error correction for speech user interfaces", *ACM TOCHI* 8(1):60–98. https://dl.acm.org/doi/10.1145/371127.371166

**Finding.** When correcting by respeaking, users hyperarticulate ("co-articulated / exaggerated") speech — sometimes even *preemptively*, before an error occurs — and isolated-word corrections are especially error-prone for recognizers. Vertanen, 2006 — "Speech and speech recognition during dictation corrections", *Interspeech 2006*. https://www.isca-archive.org/interspeech_2006/vertanen06_interspeech.html (DOI: 10.21437/Interspeech.2006-520)

**Finding.** The *usefulness of touch-based correction UIs* (e.g., n-best alternate lists) depends on the word-error-rate regime: at low WER, lightweight inline fixes suffice; at high WER, richer alternates lists earn their space. Murad, Munteanu & Stuerzlinger, 2019 — "Effects of WER on ASR Correction Interfaces for Mobile Text Entry", *MobileHCI '19*. https://www.christinemurad.ca/publications/30946-effects-of-wer-on-asr-correction-interfaces-for-mobile-text-entry (author copy: https://www.cs.toronto.edu/~cmurad/docs/speech_correction_mobilehci_author_copy.pdf)

> **Design implications for SayItErmano:**
> - After insertion, make the *last few utterance segments* one click/tap away in the pill or a quick popover (n-best alternates for the low-confidence segment), instead of forcing users to re-dictate the whole phrase — re-dictation is the empirically slower path (Suhm et al.).
> - Offer a visible "history window" path back into the last transcription with inline re-edit, so correction never requires re-recording.
> - Expect hyperarticulation: if the user immediately re-speaks after seeing a bad insert, treat the retry as possibly exaggerated speech and consider showing "correct by voice or by keyboard?" as an explicit choice.
> - If per-segment confidence is available from Whisper, surface alternates only for the segments most likely wrong (Murad et al.: rich correction pays off where errors concentrate).

---

## 5. Trust and confidence display: show calibrated uncertainty

**Finding.** The foundational automation-trust framework: trust should be *calibrated* to actual capability (avoiding both overtrust/misuse and undertrust/disuse); operators continuously appraise system performance, process, and purpose. Lee & See, 2004 — "Trust in Automation: Designing for Appropriate Reliance", *Human Factors* 46(1):50–80. https://journals.sagepub.com/doi/10.1518/hfes.46.1.50_30392 (also https://pubmed.ncbi.nlm.nih.gov/15151155/)

**Finding.** Displaying a context-aware system's uncertainty helped users calibrate trust appropriately (trust effects depended on the system's actual accuracy — displayed uncertainty with a reliable system improved trust; with an unreliable one it exposed it). Antifakos, Schwaninger & Schiele, 2004 — "Evaluating the Effects of Displaying Uncertainty in Context-Aware Applications", *UbiComp 2004*, pp. 54–69. (Verified via program listing: https://ubicomp.org/ubicomp2004/prg.php?show=papers_technotes and DBLP: https://dblp.org/db/conf/huc/ubicomp2004)

**Finding.** Follow-up: explicitly displaying system confidence is a lever for improving trust in context-aware systems. Antifakos, Kern, Schiele & Schwaninger, 2005 — "Towards Improving Trust in Context-Aware Systems by Displaying System Confidence", *UbiComp 2005*. (Verified full text: https://pure.mpg.de/rest/items/item_1791319_3/component/file_3175255/content)

> **Design implications for SayItErmano:**
> - Map confidence to *calm, ordinal* cues, not raw numbers: e.g., a small 1–3 dot confidence strip on the inserted-text badge, or a low-contrast underline for shaky words in the history view. Never fake high confidence.
> - Because displayed uncertainty exposes real quality, pair it with an easy correction affordance (Section 4) — uncertainty display only builds calibrated trust when repair is one step away (Lee & See's "appropriate reliance").
> - For the rewrite mode, distinguish visually between "verbatim transcription" and "LLM-rewritten" output; conflating them miscalibrates trust in both.

---

## 6. Motion and micro-interaction science: timing, principles, and perceived speed

**Finding.** The 0.1 / 1 / 10 s "cost of knowledge" axiom: any action to reach information should complete within 0.1 s (perceptual immediacy), 1 s, or 10 s — the origin of animation-duration budgeting in interactive systems. Card, Robertson & Mackinlay, 1991 — "The Information Visualizer, an Information Workspace", *CHI '91*, pp. 181–188. https://dl.acm.org/doi/10.1145/108844.108874

**Finding.** Animation principles from traditional animation transfer directly: *timing* (few frames read as fast/energetic, many as slow/languid), *secondary action* and *appeal* make simple motion feel alive and intentional. Lasseter, J., 1987 — "Principles of traditional animation applied to 3D computer animation", *Computer Graphics (SIGGRAPH '87)* 21(4):35–44. https://dl.acm.org/doi/10.1145/37402.37407 (PDF: http://www.cs.cmu.edu/afs/cs/academic/class/15462-f13/www/lec_slides/Lesseter.pdf)

**Finding.** Loading-screen animation *speed* measurably changes perceived waiting time — faster-cadenced motion changes the felt duration of identical waits. Söderström, Bååth & Mejtoft, 2018 — "The Users' Time Perception: The effect of various animation speeds on loading screens", *ECCE '18*. https://dl.acm.org/doi/10.1145/3232078.3232092

*Unverified-by-primary-source note:* the oft-quoted "UI transitions should run 100–300 ms with standard easing curves" is a practitioner convention (Material/HIG guidance and NN/g articles), not a specific peer-reviewed result located in this pass; it is consistent with the 0.1 s immediacy threshold (Card et al. 1991; Miller 1968) but cite it as convention, not science.

> **Design implications for SayItErmano:**
> - Budget the pill: appear/expand ≤ 150 ms and start the waveform immediately (inside the 0.1 s "instant" band); collapse/success badge ~200–300 ms; no transition in the pill should ever block input for more than ~1 s.
> - Cadence matters more than flourish: recording pulse and processing shimmer should be quick and rhythmic (perceived-fast), while the success badge gets slightly slower, spring-like motion (Lasseter's timing/secondary-action/appeal) to read as a satisfying "landing".
> - Animate *state changes* (idle→recording→processing→inserted), not idle idle-states; a constantly looping idle animation dilates perceived time when the user is waiting for the pill to react.

---

## 7. Delight and affect: engineer the peak and the end; watch the uncanny valley

**Finding.** Retrospective judgment of an experience is dominated by its *peak* moment and its *end*, not its average or duration (the cold-water experiment; people chose to repeat a longer aversive episode that ended better). Kahneman, Fredrickson, Schreiber & Redelmeier, 1993 — "When More Pain Is Preferred to Less: Adding a Better End", *Psychological Science* 4(6):401–405. https://journals.sagepub.com/doi/10.1111/j.1467-9280.1993.tb00589.x

**Finding.** Cuteness ("kawaii") triggers positive affect that promotes *careful* behavior and narrows attentional focus — cute aesthetics can plausibly improve care during precision tasks. Nittono, Fukushima, Yano & Moriya, 2012 — "The Power of Kawaii: Viewing Cute Images Promotes a Careful Behavior and Narrows Attentional Focus", *PLoS ONE* 7(9):e46362. https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0046362

**Finding.** The uncanny-valley risk: affinity rises with human-likeness until an almost-but-not-quite-human point where response plunges to eeriness — a standing risk for mascot/avatar designs that lean anthropomorphic. Mori, M., 1970; authorized English translation by MacDorman & Minato, 2012 — "The Uncanny Valley [From the Field]", *IEEE Robotics & Automation Magazine* 19(2):98–100. https://spectrum.ieee.org/the-uncanny-valley (bibliographic record: http://ui.adsabs.harvard.edu/abs/2012IRAM...19b..98M/abstract)

> **Design implications for SayItErmano:**
> - The peak-end of every dictation cycle is the insert moment: invest motion and polish budget in the final "text landed" badge (a small pop + checkmark + brief accent), because that beat disproportionately colors how the whole interaction is remembered.
> - End states should never be silent (pill just vanishing): a decisive, friendly completion beat converts "waiting" into "finished well" even when transcription was imperfect.
> - A mascot, if any, should be stylized-abstract (a simple blob/shape like the current pill), not quasi-human; keep it minimal and let it disappear between uses so it cannot curdle from charming to eerie or distracting (Mori; Nittono supports cuteness *plus* task focus, not cuteness that competes for attention).

---

## 8. Accessibility: motion safety, reduced-motion support, glanceability

**Finding.** WCAG 2.1 Success Criterion 2.3.3 "Animation from Interactions" (Level AAA): motion animation triggered by interaction must be disable-able unless essential; the CSS `prefers-reduced-motion` media query is the standard mechanism. W3C — "Understanding SC 2.3.3: Animation from Interactions", *WCAG 2.1*. https://www.w3.org/WAI/WCAG21/Understanding/animation-from-interactions (Quick Ref: https://www.w3.org/WAI/WCAG22/quickref/)

**Finding.** Sensitivity to motion-parallax cues predicts motion-sickness severity — movement in peripheral vision genuinely sickens a subset of users (cybersickness literature applies to background UI motion, not just VR). Fulvio et al., 2021 — "Variations in visual sensitivity predict motion sickness symptoms", *Journal of Eye Movement Research*. https://www.sciencedirect.com/science/article/pii/S1875952121000203 (practitioner account: https://alistapart.com/article/accessibility-for-vestibular/)

**Finding.** Glanceability — reading a display's state in a single brief glance with minimal interruption to a primary task — is the defining design goal for peripheral displays, with guidelines built on pre-attentive abstraction (change detection, feature extraction, symbolism). Matthews, T., 2006 — "Designing and Evaluating Glanceable Peripheral Displays", *DIS 2006*. https://www.semanticscholar.org/paper/9a062705d4d3149321f63fcfac2cd842a2142508 (ACM: https://dl.acm.org/doi/10.5555/1354857; also Matthews, Forlizzi & Rohrbach, UC Berkeley tech report UCB/EECS-2006-113: https://www.semanticscholar.org/paper/ec50a6a68a5abd5ef866177372e0f91125224d4f)

> **Design implications for SayItErmano:**
> - Honor `prefers-reduced-motion` in GTK (via `GtkSettings:gtk-enable-animations` plus detecting the portal/setting): replace waveform undulation, pulsing, and shimmer with static color states; the success badge becomes a static check rather than a pop. An overlay that moves in peripheral vision is exactly the parallax-adjacent case the vestibular literature warns about.
> - Never move the pill *itself* (no repositioning, no parallax drift) while the user is typing elsewhere — keep motion within the pill's bounds.
> - Design every pill state to be readable in one glance: one dominant color signal per state, high contrast against both light and dark GNOME themes (per WCAG contrast requirements, see the W3C Quick Ref above), and a fallback icon/label (e.g., screen-reader-accessible state text) so state is never conveyed by color or motion alone.
> - The tray icon should mirror the pill's state (recorded vs idle) with a tooltip, extending the same glanceable vocabulary to the periphery.

---

## Top 10 highest-leverage findings (ranked)

1. **Respond inside the human turn-taking gap:** flip idle→recording in <200 ms so hotkey-to-live feels conversational. (Stivers et al., 2009, *PNAS*)
2. **Keep all state feedback within the 0.1 s "instant" band**; anything ≥1 s needs animated progress, ≥4 s needs an explicit still-working cue. (Miller, 1968, AFIPS; Card et al., 1991, CHI; Maslych et al., 2025, CUI)
3. **Never show a dead pill during Whisper/LLM processing:** users prefer short working signals over zero-signal, and fillers/streaming cut perceived latency. (Maslych et al., 2025, CUI; Iftikhar et al., 2023, CHI; Abbas et al., 2022, CSCW2)
4. **Engineer the end beat:** the insert/success badge is the peak-end of every cycle — a polished completion animation disproportionately improves the remembered experience. (Kahneman et al., 1993, *Psychological Science*)
5. **Multimodal correction beats re-dictation:** give one-tap access to recent segments and n-best alternates instead of forcing users to re-speak; expect hyperarticulated retries. (Suhm, Myers & Waibel, 2001, *TOCHI*; Vertanen, 2006, Interspeech; Karat et al., 1999, CHI)
6. **Make the mic state perceptibly unambiguous:** the pill is the privacy indicator; distinct, high-salience recording vs. armed states, with consistent meanings per animation. (Do et al., 2023, USENIX Security; Kunchay et al., 2021, ICMI)
7. **Fill and structure waiting time:** accelerating, fine-grained progress and skeleton/ghost text make identical waits feel shorter; labeled stages ("transcribing → rewriting") keep unexplained-wait anxiety down. (Harrison et al., 2010, CHI; Ziat et al., 2022, *Scientific Reports*; Mejtoft et al., 2018, ECCE; Maister, 1985)
8. **Display calibrated confidence:** ordinal, honest confidence cues next to inserted text (paired with one-step repair) build appropriate reliance instead of blind trust. (Lee & See, 2004, *Human Factors*; Antifakos et al., 2004/2005, UbiComp)
9. **Honor reduced motion and design for glanceability:** static-state fallbacks for vestibular safety, no peripheral-motion triggers, one-glance readable states with icon+label fallbacks. (W3C WCAG 2.1 SC 2.3.3; Fulvio et al., 2021, *JEMR*; Matthews, 2006, DIS)
10. **Time motion like an animator, budget like Card:** 100–300 ms transitions, fast-cadenced pulse while listening, springy success landing, stylized-abstract (never quasi-human) mascot. (Lasseter, 1987, SIGGRAPH; Söderström et al., 2018, ECCE; Mori, 1970/2012, *IEEE RAM*)

---

## Verification notes

- All citations above were checked against at least one fetched or search-confirmed page carrying title, authors, year, and venue. URLs point to the verified page (ACM DL, PNAS, SAGE, PLOS, PMC, USENIX, ISCA, W3C, IEEE, arXiv, or publisher/author pages).
- Weaker/caveated items, kept only with flags: Doherty & Thadhani (1982) is an IBM technical report, not peer-reviewed (scanned copy verified); Nielsen (1993) is authoritative practitioner material used as secondary support; Guerra & Milanese (2024) has partially confirmed venue details; the "100–300 ms transition" convention is practitioner practice, not a located peer-reviewed result.
- Dropped as unverifiable in this pass: the "operational vs reactive wait / 'Myersummers'" reference from the research brief; any specific peer-reviewed study of live-waveform effects on dictation confidence (flagged as an evidence gap in Section 3).
