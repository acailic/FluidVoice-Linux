# Native settings & history app (replaces the web UI) — design

Date: 2026-09-02
Status: awaiting user review
Parity target: upstream macOS app windows (`ContentView` + `TranscriptionHistoryView`,
`SettingsView` + AI settings screens, `WelcomeView`/onboarding steps)

## Problem

Settings, History, and Onboarding live in HTML pages served by the daemon on
127.0.0.1 and open in a **browser tab** (`xdg-open`). The user wants a real
separate app — like the macOS app's own windows — not a web page.

## Decision

**Build a native GTK 4 + libadwaita app as a separate process. Remove the web
UI entirely (HTTP server and HTML pages).**

The daemon keeps owning state and validation; the app is a GTK client that
talks to it over the **existing unix control socket** and reads local data
(history JSONL, config) through the shared Python modules. No TCP listener
remains on 127.0.0.1.

Alternatives considered:

- **Wrap the existing pages in pywebview** — least work, but adds a
  dependency, keeps the web tech the user asked to move away from, and still
  looks like a framed web page. Rejected.
- **Native app + keep the web UI as fallback** — doubles UI maintenance
  forever (every knob built twice). Rejected; headless boxes keep the CLI
  (`fluidvoice config print/init`, `fluidvoice doctor`).

Why GTK4: GNOME is the dev/test desktop; GTK 4.14 + libadwaita 1.5 +
PyGObject are already installed system-wide; the codebase already uses `gi`
(tray GLib loop). The deb's bundled venv is created with
`--system-site-packages`, so system `gi` is importable there too.

## Architecture

```
┌─────────────────────────────┐        unix socket (JSON lines)       ┌──────────────┐
│ fluidvoice app (GTK4/Adw)   │ ────────────────────────────────────▶ │ daemon       │
│  main window   = History    │   status / toggle / test-dictation /  │  (unchanged  │
│  settings wind.= Settings   │   get-config / set-config /           │   core loop) │
│  onboarding    = Welcome    │   select-model                        │              │
└──────────┬──────────────────┘                                        └──────────────┘
           │ direct (same user, same files)
           ▼
   history.py (search/delete/clear/audio) · config.py (load) ·
   backends (model catalog, downloaded check) · ai.client (test AI)
```

### New package `fluidvoice/gtkui/`

One GtkApplication, app id `dev.fluidvoicelinux.FluidVoice`, single-instance
via GApplication (a second launch just tells the primary instance which
window to raise — the standard Gtk.Application pattern).

- `application.py` — Gtk.Application subclass: window registry, remote
  activation (`--open history|settings`), Adw init, optional-import guard
  (no GTK → clear stderr hint `apt install python3-gi gir1.2-gtk-4.0
  gir1.2-adw-1`, exit 1).
- `main_window.py` — History (macOS main-window counterpart): live status
  header (state dot, backend, GPU, model, warmup progress/error), search
  bar, entry cards (time, duration, app, mode, AI badge), copy / delete /
  clear-all, inline audio replay via GtkMediaFile (GTK's GStreamer backend),
  fallback "open externally" (xdg-open) if media init fails.
- `settings_window.py` — sidebar sections (Adw preferences style):
  **General** (language, copy-to-clipboard, tray, notifications, sounds +
  volume), **Models** (catalog grid, download & switch, warmup state,
  backend/device/compute), **AI Polish** (enabled, base URL, model, key env
  var, temperature, test-connection, per-app prompt rows — see below),
  **Dictation** (hotkey + mode + cancel key, mic picker, insertion mode,
  spoken punctuation + prefix, filler removal, skip-silent, max seconds,
  media pause, preview settings), **History** (save, save audio, budget,
  clear), **About** (version, backend, CUDA).
  Covers everything the web Settings page exposes today — including the
  in-flight `recording.pause_media` (MPRIS pause) and
  `ai.per_app_prompts` (per-app prompt sets) knobs — plus the cheap extras
  already covered by the validator tables.
- `onboarding.py` — Welcome flow (mic, model, hotkey, AI checks + a real
  3 s tryout via socket `test-dictation`; writes the `.onboarded` marker).
- `client.py` — thin wrapper: socket calls via `control.request` with
  friendly errors; direct reads via `history`/`config`/`backends`;
  daemon-liveness probe.

Deliberately **not** in v1 (config stays file-editable, UI links to the
file path): custom-dictionary editor, filler-word list editor. Per-app
prompts get a minimal editor (list of "app match + instructions" rows)
because that feature is landing in parallel and must not regress when the
web UI is deleted; richer upstream-style prompt profiles stay on the
roadmap.

### Daemon changes

- New socket actions in `handle_request` (transport already exists in
  `control.py`; JSON lines, 10–15 s timeouts, warmup runs in a thread so
  responses stay fast):
  - `get-config` — live daemon cfg, `ai.api_key` masked to a bool
    (same rule as today's `/api/config`).
  - `set-config` — validated merge into the **live** cfg + `save_config`;
    returns `{changed, rejected, note}` (same semantics as the web
    endpoint: some keys apply after restart).
  - `select-model` — moved from `WebUI._warmup_model`: background warmup,
    persist + hot-swap the backend on success, roll back on failure.
  - `status` — extended with `warmup` state; `webui_port` dropped.
- The validation layer (`_VALIDATORS` / `_ENUMS` / `_BOOLS` / `_coerce` /
  allowed sections) moves from `webui.py` into **`config.py`** as
  `apply_settings(cfg, body) -> (changed, rejected)` — one source of truth
  used by the daemon action and unit tests.
- Tray menu "Settings…" / "History" and first-run onboarding spawn /
  activate the app (`fluidvoice app --open settings|history`,
  `fluidvoice app --onboard`) instead of `xdg-open http://…`.
- `webui.py` deleted; `server.enabled/port` config section removed
  (loader silently strips it from old configs). `doctor.py` webui check
  becomes a GTK-availability check.

### CLI / desktop integration

- New: `fluidvoice app [--open history|settings] [--onboard]`.
- `fluidvoice settings` becomes an alias for `fluidvoice app --open
  settings` — the existing `.desktop` entry (`Exec=fluidvoice settings`)
  keeps working and now opens the native window; StartupNotify=true so
  GNOME shows the launch feedback.
- pyproject gains **no new pip deps** (PyGObject comes from the system);
  deb `Depends` adds `gir1.2-gtk-4.0`, `gir1.2-adw-1`, `python3-gi`.

## Data flow (examples)

- **Save settings**: window collects values → `set-config` over socket →
  daemon validates via `apply_settings`, mutates live cfg, saves TOML →
  app shows changed/rejected keys. AI/sounds/etc. apply immediately, same
  as the web UI today.
- **Model switch**: Models section → `select-model` → daemon warms up in a
  thread → app polls `status.warmup` every 2 s → on success the running
  daemon hot-swaps the backend; on failure the previous model stays and
  the error is shown.
- **History browse/search**: `client.py` calls `history.search()` directly
  (local file, same user). Delete/clear likewise. No daemon round-trip.
- **Onboarding tryout**: `test-dictation` socket action (already exists) —
  nothing is typed anywhere, identical to today's web tryout.

## Degraded & error handling

- **Daemon not running**: persistent banner in both windows; History fully
  usable; Settings switches to file-only mode — saves go straight to
  `save_config` and apply on next daemon start (banner says so); toggle /
  test-dictation / model switch disabled.
- **Socket timeout / garbled reply** → "daemon not responding" banner, retry.
- **Warmup failure** → error string in the status header and Models section;
  previous model kept (today's rollback behavior).
- **Rejected keys** → listed in the save feedback, nothing half-applied.
- **No GTK on the machine** → clear install-hint error (see guard above);
  daemon and all CLI features are unaffected.

## Security

The entire localhost attack surface goes away: no TCP listener, no CSRF /
DNS-rebinding guards to maintain — only the pre-existing user-owned unix
socket (`$XDG_RUNTIME_DIR`), which already granted `toggle`/`shutdown`.
`set-config` adds no new trust boundary (same local user). The api-key
masking rule (`get-config` never returns the value) is preserved.

## Testing

- Unit: `apply_settings` validator behavior (ported from the webui test
  suite's API halves), client wrapper against a fake socket, daemon
  `handle_request` for the new actions (fake backend factory, like
  existing daemon tests).
- Offscreen GTK smoke tests (windows instantiate and populate from fixture
  data; skip when no display is available) — default suite stays green on
  headless CI.
- `desktop`-marked live check: launch the app against a stub daemon,
  screenshot both windows (same pixel-proof loop the overlay used).
- Integration: `test_daemon_http.py` is replaced by socket-action coverage.

## Docs & ledger updates

STATUS.md (feature table), ROADMAP.md ("Settings UI" entry → native app;
drop the web mention), UPSTREAM-TRACKING.md (rows for settings chrome and
"Adaptive light/dark theming" → ✅ native window follows the system theme),
README (screenshots later), doctor output.

## Build order (for the implementation plan)

1. `apply_settings` in config.py + new socket actions + daemon-side
   warmup/select-model move (webui still present; suite green). The
   in-flight per-app-prompts / MPRIS-pause WIP (uncommitted as of this
   spec) lands first or is absorbed here — the consolidated validator
   tables must cover its new keys.
2. `gtkui` package: client → application skeleton → settings window →
   history window → onboarding; CLI + tray + first-run spawning.
3. Delete `webui.py`, `server` config section, webui tests → migrate;
   doctor/CLI cleanup; docs + deb Depends.
4. Live desktop verification (screenshot gates) + parity ledger updates.

## Out of scope

Parakeet/streaming models, Wayland insertion, dictionary/per-app-prompt
editors, ZIP export, stats page, upstream's local HTTP API (`/v1/…`).
