# Product improvement proposals — 2026-09-04

Menu for factory briefing. Each entry: evidence → scope sketch → effort (S/M/L) → risk.
Effort assumes the SSSF phase model (each phase leaves the offline suite green).
Sources: ROADMAP.md open rows, UPSTREAM-TRACKING.md gaps, STATUS.md residuals,
today's live diagnosis session (hotkey-grab incident), and a history.jsonl audit.

---

## P1 — Self-healing hotkey grabs (trust: the product must never silently die)

**Evidence (live, today):** at login a second daemon (stale fluidvoice-linux 0.2.1
deb) won the XGrabKey race for Right_Control; the v0.5.0 daemon's 8 lock-mask
grabs were refused (8× BadAccess, GrabKey) and it stayed "ready" with a **dead
hotkey** until manually restarted. `HotkeyListener` retries only the cancel key
(`_sync_cancel_grab`, hardened in c720b25); the main grab in `setup()` has no
retry and no warning. Grab health is invisible to doctor/tray/status.

**Scope:**
1. `hotkey.py`: route grab BadAccess through an installable error handler
   (python-xlib delivers it via the default handler, NOT an exception — proven
   live today); track per-combo grab state.
2. Re-grab loop: piggyback `_sync_cancel_grab`'s 10 ms poll — attempt missing
   combos; stop trying after N failures with one WARN.
3. Surface: startup WARN + notification when the initial grab is refused
   ("hotkey held by another client — will retry"); `doctor` line (grab owner
   state); tray tooltip suffix when unhealthy.
4. Tests: unit-test the handler routing with a fake display; integration test
   with a deliberate conflicting grab.

**Effort:** S–M. **Risk:** low. **Why now:** a dead hotkey is a dead product,
and today proved the failure mode is real, silent, and user-invisible.

---

## P2 — History integrity: test pollution + honest stats

**Evidence (measured today):** 724/738 history entries are command-mode TEST
rows (`true 1`, `exit 3`, duration_ms 0–1) written by the suite into the live
`~/.local/share/sayit-ermano/history.jsonl`. conftest isolates XDG_CONFIG_HOME
but not the data dir. Consequence: `status` "today: 333 dictations" (332 were
tests), History window, today-header, and ZIP export all lie on a dev machine;
worse, the same leak would corrupt a user's real history if tests ever run
outside dev.

**Scope:**
1. conftest: isolate the data dir (env/paths override for history + audio);
   audit every test that constructs the real paths module.
2. Migration/cleanup: one-off scrub of obvious test rows (mode=command,
   command in {true 1, true 2, exit 3…} set) or a documented manual purge —
   decide during planning; backup first.
3. Hardening: `history.append` refuses entries with duration_ms < 1 and
   non-string commands? No — better: daemon-side is fine; the leak is the test
   env. Keep the fix at isolation + a regression test asserting the real file's
   mtime/size is untouched by a suite run.
4. doctor: history sanity line (entries, size, oldest).

**Effort:** S. **Risk:** low. **Why now:** every other metric-driven decision
(and the History UX) depends on trustworthy data; this also unblocks future
usage-driven prioritization.

---

## P3 — Wayland session support (v0.3 milestone: reach multiplier)

**Evidence:** ROADMAP v0.3 fully open (insertion via ydotool/wtype +
wlr virtual-keyboard, DE-shortcut binding docs per compositor, wl-clipboard
with restore). Upstream tracking marks Wayland insertion 🚧. GNOME/KDE default
to Wayland; Pop!_OS is moving (COSMIC). Today the app is X11-only end-to-end.

**Scope sketch (phased):**
1. Capability probe at daemon start (XDG_SESSION_TYPE) → doctor report.
2. Insertion: wtype/ydotool text path; wl-clipboard paste+restore mirroring the
   X11 verify-paste design where the compositor allows observation; terminal
   paste key handling.
3. Hotkey: no global grab on Wayland — document + assist binding a DE shortcut
   to `sayit-ermano toggle` (GNOME custom-keyword helper page in Settings);
   optional evdev listener for physical push-to-talk (uinput, needs perms).
4. Overlay: pill via a normal layer-shell/portal notification fallback first
   (wlroots layer-shell only on some compositors) — degrade gracefully.

**Effort:** L (3–5 phases). **Risk:** compositor matrix QA burden; ydotool
requires daemon+uinput permissions — document honestly. **Why:** biggest
addressable-user multiplier on the roadmap; also pre-writes the COSMIC story.

---

## P4 — Streaming/transcription engine pass (Parakeet Realtime / segmented finalization)

**Evidence:** ROADMAP links "immediate-stop countdown needs streaming VAD" to
the spoken-send row; UPSTREAM-TRACKING lists Parakeet Realtime / Nemotron 3.5
streaming 🚧 and notes streaming "unlocks tighter live preview". Current live
preview re-transcribes a growing buffer every ~1.2 s (CPU grows with take
length; no true finalization cadence). Deferred from the UI-uplift cycle.

**Scope sketch:** either true streaming engine (NeMo/Riva or community
streaming exports — dependency-heavy) OR first a segmented-finalization
rewrite of the existing whisper path (fixed 2–3 s windows, incremental decode
with prev-context, early-stop VAD gate on the tail segment). The latter is
engine-agnostic and probably the right first phase regardless.

**Effort:** M–L. **Risk:** model-quality regressions on segment boundaries;
GPU memory of parallel decodes. **Why:** perceived latency and the
interrupt/immediate-stop semantics are the biggest remaining "feel" gaps vs
upstream.

---

## P5 — Command mode v2 (voice → terminal agent)

**Evidence:** command mode shipped v1 (strict-JSON single-tool, every command
confirmed, pill overlay) and is this port's clearest differentiator vs other
Linux dictation tools; upstream parity items open: chat store, native
tool_calls schema, destructive-command confirmation list. Real usage signal is
currently unmeasurable because of P2 (history pollution hid whether/how the
user actually uses command mode).

**Scope sketch:** tool schema parity (multi-tool, args validation),
conversation store (follow-ups reference prior output), destructive-command
pattern list with explicit confirmation UX, History window command tab
(retry/copy/pin), per-app command profiles. Sequence AFTER P2 so usage data
can validate the investment.

**Effort:** M–L. **Risk:** security surface (voice-run commands) — the
confirmation UX is the product; scope creep into "build an agent" (non-goal:
stay a thin, confirm-first runner).

---

## P6 — Settings depth pack: prompt profiles, per-model language, model pruning

**Evidence:** last open v0.2 row (user-editable prompt profiles / named
presets of the base prompt); v0.4 rows (per-model language selection —
whisper/cohere/nemotron stores upstream; model-manager prune/free). All are
visible Settings gaps with upstream references.

**Scope:** named presets CRUD over the existing base-prompt editor; language
key per model entry + passing to backends; "free disk space" action in the
Models page (delete non-active model dirs with confirm).

**Effort:** S–M. **Risk:** low; pure additive UI + config plumbing.

---

## P7 — Auto-update + packaging breadth (distribution maturity)

**Evidence:** ROADMAP "Auto-updater (or packaged releases); onboarding" open;
AUR/nix/pipx open (deb done). Live incident today: the machine was upgraded to
0.5.0 by hand-pipping into the relocated venv while the old 0.2.1 deb kept
autostarting — the exact failure an updater prevents. GitHub releases exist
(v0.4.0, v0.5.0); Reddit post already points at the install URL.

**Scope sketch:** start-stop update check against GitHub releases (opt-in),
desktop notification with release notes, one-action upgrade (download deb →
apt install via pkexec, or in-place venv refresh for user installs);
packaging: AUR recipe + pipx/PYPI packaging hygiene (entry points, data);
onboarding refresh pass afterwards.

**Effort:** M. **Risk:** update-mechanism trust (signing/checksums); keep
manual-only CI workflows per project rule (no auto-publish).

---

## P8 — Mouse push-to-talk + lock/screen-saver suppression (parity, small)

**Evidence:** upstream PR #939 (mouse-button hotkeys, interrupted holds) is
triaged ⏳ in UPSTREAM-TRACKING; ROADMAP "Later" row explicitly names
XGrabButton + button-state polling + "suppressing hotkeys while the screen is
locked".

**Scope:** XGrabButton button push-to-talk mirroring the hold-mode
passthrough design (query-pointer polling), lock-state watch
(logind PrepareForSleep/Lock + screensaver D-Bus) to ignore hotkeys while
locked, config keys + doctor lines.

**Effort:** S–M. **Risk:** low; X11-only (pairs with P3's Wayland story).

---

## Suggested sequencing

1. **P1 + P2** immediately (small, trust-restoring; P2 also unblocks honest
   usage analytics for every later decision).
2. Then the strategic fork — pick ONE: **P3** (reach: Wayland), **P5**
   (depth: command mode, after P2 validates usage), or **P4** (feel:
   streaming). P3 recommended: the X11-only ceiling is the largest structural
   limit, and today's grab-race class of bugs is X11-grab-inherent.
3. **P6 / P7 / P8** as palate-cleansers between big phases (each is
   independently shippable).

## Status 2026-09-05

- **DONE:** P1 (23e2567), P2 (634dbca), P6 (93e21b2), P7 (55c2062),
  P8 (c2a95f6).
- **P5 in progress** (user, overnight 09-05): multi-tool protocol +
  destructive-command list landed (03d243f, 3576ae0; spec
  specs/d13f4d53_command-mode-v2.md). Remaining: conversation store,
  History Commands tab.
- **P4 picked next** — streaming preview (segmented finalization, phase 1
  only) as Phase A of the "macOS parity and beyond" cycle
  (docs/superpowers/specs/2026-09-05-macos-parity-and-beyond-design.md);
  the fork is effectively being answered in order P5 → P4 → P3, with P3
  (Wayland) the recommended cycle after this one — the upstream official
  Linux build ("coming soon", reviews doc insight 11) keeps the window
  time-boxed.
