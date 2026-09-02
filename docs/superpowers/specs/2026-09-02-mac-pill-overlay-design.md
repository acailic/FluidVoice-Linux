# Mac-style recording overlay for FluidVoiceLinux

Design date: 2026-09-02
Goal: replace the primitive X11 text-bar preview with a faithful Linux port of
the macOS app's recording overlay (studied at https://altic.dev/fluid and in the
upstream SwiftUI sources, `altic-dev/Fluid-oss` → `Sources/Fluid/Views/BottomOverlayView.swift`).

## Extracted Mac design spec (source of truth: upstream Swift code)

- Position: bottom-center of the screen, small offset above the bottom edge.
- Pill (idle / no text): **solid black stadium** (46 pt tall, corner radius 23),
  1.2 pt white gloss border (angular-gradient highlight, animated), soft black
  drop shadow. Content row: app icon (18 pt) + waveform + mode label
  ("Dictate", white 85%, semibold).
- Waveform: 8 white bars (width 3, spacing 2.5, heights 4–28, rounded caps,
  white at 88% opacity) driven by the **live audio level**; during processing
  the bars flatten to minimum and a shimmer sweep runs across them.
- With transcription text (small/medium sizes): black rounded rect (radius 14–18)
  with the live text (white 90%, medium weight, 11–13 pt) above the waveform
  row, single line, head-truncated with "…".

## Linux approach

New module `fluidvoice/overlay.py`:

1. **`PillRenderer`** — pure-Pillow frame renderer (headless, unit-testable).
   Renders at 2× and downsamples with Lanczos for anti-aliased corners/bars/text.
   Produces RGBA frames + rounded-corner mask. Handles states: `recording`
   (bars from level array), `processing` (flat bars + sweeping shimmer),
   and optional preview text row. Uses DejaVu Sans (with PIL default fallback).
2. **`AudioLevels`** — maps the tail of the raw PCM capture (8 × ~60 ms windows)
   to per-bar target heights (RMS × gain, clamp 4–28 px), with fast-attack /
   slow-release smoothing so the bars feel like the Mac visualizer.
3. **`FluidOverlay`** — X11 override-redirect window (never steals focus),
   bottom-center anchored, ~25 fps render thread, rounded corners via the X11
   shape extension (works without a compositor since the Mac pill is solid
   black anyway). Frame updates via background pixmap. Shows immediately at
   recording start (idle waveform before first text). Any failure (no X11,
   no Pillow, no font) falls back to the existing `NotifyPreview`, preserving
   the current graceful-degradation behavior.
4. **Brand icon** — ship the FluidVoice app icon (`fluidvoice/assets/icon.png`)
   rendered rounded in the pill where the Mac build shows the target-app icon.

## Wiring

- `daemon.py`: `preview_mode` gains `"auto"` (new default): try the pill
  overlay, fall back to notify. Overlay starts at recording start; on stop it
  enters the processing state and closes once transcription/insertion finishes
  (cancel/error close it immediately; a hard cap auto-closes a stuck overlay).
- `config.py` + `webui.py`: enum `{"auto", "overlay", "notify"}`.
- `preview.py`: `PreviewEngine`/`NotifyPreview` unchanged; the old
  `X11OverlayPreview` is removed in favor of `overlay.FluidOverlay`.

## Testing

- `tests/test_overlay.py`: renderer geometry/colors (stadium radius, black
  fill, white bar pixels, text truncation, shimmer state), `AudioLevels`
  smoothing + silence/clip behavior, fallback paths without a display.
- `tests/integration/test_live_x11.py`: updated to pixel-verify the new pill.
