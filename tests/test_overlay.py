"""Mac-style pill overlay renderer tests (headless - no X11 needed)."""
from __future__ import annotations

import math
import struct

import pytest

from fluidvoice.overlay import (BAR_COUNT, BAR_MAX_H, BAR_MIN_H, PILL_H,
                                PILL_RADIUS, AudioLevels, CommandPanel,
                                FluidOverlay, PillRenderer, head_truncate)


def sine(seconds: float = 1.0, rate: int = 16000, freq: int = 220,
         amp: int = 20000) -> bytes:
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate)))


def bright_pixels(img, region=None, step=2, threshold=150) -> int:
    g = img.convert("L")
    xs = range(region[0], region[2], step) if region else range(0, img.width, step)
    ys = range(region[1], region[3], step) if region else range(0, img.height, step)
    return sum(1 for x in xs for y in ys if g.getpixel((x, y)) > threshold)


class TestPillGeometry:
    def test_idle_pill_matches_mac_spec(self):
        r = PillRenderer(size="pill")
        w, h, radius = r.inner_size(None)
        assert h == PILL_H
        assert radius == PILL_RADIUS  # stadium: height / 2
        assert w >= 100               # icon + waveform + label fit

    def test_text_grows_pill_and_switches_radius(self):
        r = PillRenderer(size="small")
        w0, h0, _ = r.inner_size(None)
        w1, h1, radius = r.inner_size("hello world")
        assert h1 > h0
        assert radius == 14  # small-size rounded rect (upstream constant)
        assert w1 >= w0

    def test_pill_size_hides_streaming_text(self):
        # upstream: the pill size shows no preview text
        r = PillRenderer(size="pill")
        w0, h0, _ = r.inner_size(None)
        w1, h1, _ = r.inner_size("lots of streaming words")
        assert (w0, h0) == (w1, h1)

    def test_size_presets_follow_mac_constants(self):
        from fluidvoice.overlay import DEFAULT_SIZE, SIZE_SPECS
        assert DEFAULT_SIZE == "medium"  # upstream default
        pill = SIZE_SPECS["pill"]
        assert (pill.bars, pill.wave_w, pill.wave_h, pill.radius) == (8, 46, 30, 23)
        large = SIZE_SPECS["large"]
        assert (large.bars, large.bar_w, large.wave_h) == (11, 5.0, 48)
        assert large.text_lines == 4      # upstream 92pt preview box
        small = SIZE_SPECS["small"]
        assert small.text_lines == 1

    def test_medium_wraps_to_two_lines(self):
        r = PillRenderer(size="medium")
        lines = r.text_lines(
            "the quick brown fox jumps over the lazy dog again and again")
        assert 1 < len(lines) <= 2
        w, h, _ = r.inner_size(
            "the quick brown fox jumps over the lazy dog again and again")
        assert h > 60  # two text lines + waveform row

    def test_corners_transparent_center_opaque(self):
        r = PillRenderer()
        img, (w, h) = r.render([BAR_MIN_H] * BAR_COUNT, None)
        a = img.getchannel("A")
        m = PillRenderer.MARGIN
        pw, ph, _ = r.inner_size(None)
        assert a.getpixel((m + 1, m + 1)) < 40             # rounded corner cut
        assert a.getpixel((m + pw - 2, m + ph - 2)) < 40   # opposite corner
        assert a.getpixel((m + pw // 2, m + ph // 2)) > 200  # center solid

    def test_shadow_fades_inside_margin(self):
        r = PillRenderer()
        img, (w, h) = r.render([BAR_MIN_H] * BAR_COUNT, None)
        a = img.getchannel("A")
        edges = [(0, h // 2), (w - 1, h // 2), (w // 2, 0),
                 (w // 2, h - 1), (0, 0), (w - 1, h - 1)]
        assert all(a.getpixel(p) == 0 for p in edges), "shadow clipped at frame edge"


class TestPillPainting:
    def test_loud_bars_brighter_than_idle(self):
        r = PillRenderer()
        m = PillRenderer.MARGIN
        quiet, _ = r.render([BAR_MIN_H] * BAR_COUNT, None)
        loud, _ = r.render([BAR_MAX_H] * BAR_COUNT, None)
        pw, ph, _ = r.inner_size(None)
        region = (m, m, m + pw, m + ph)
        assert bright_pixels(loud, region) > bright_pixels(quiet, region)

    def test_preview_text_paints_white_row(self):
        r = PillRenderer()
        text = "preview words appear here"
        img, _ = r.render([BAR_MIN_H] * BAR_COUNT, text)
        m = PillRenderer.MARGIN
        w, h, _ = r.inner_size(text)
        # text occupies the strip under the top padding
        strip = (m, m, m + w, m + 30)
        assert bright_pixels(img, strip) > 10

    def test_processing_shimmer_animates(self):
        r = PillRenderer()
        img0, _ = r.render([BAR_MAX_H] * BAR_COUNT, None,
                           processing=True, phase=0.0)
        img1, _ = r.render([BAR_MAX_H] * BAR_COUNT, None,
                           processing=True, phase=0.5)
        assert bright_pixels(img0) != bright_pixels(img1)

    def test_head_truncate_keeps_tail(self):
        from PIL import Image, ImageDraw
        r = PillRenderer()
        d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
        out = head_truncate(d, "old words " * 40, r._text_font, 300)
        assert out.startswith("…")
        assert out.endswith("words ")
        assert d.textlength(out, font=r._text_font) <= 300

    def test_fade_alpha_darkens_frame(self):
        r = PillRenderer()
        full, _ = r.render([BAR_MIN_H] * BAR_COUNT, None, alpha=1.0)
        half, _ = r.render([BAR_MIN_H] * BAR_COUNT, None, alpha=0.4)
        m = PillRenderer.MARGIN
        pw, ph, _ = r.inner_size(None)
        region = (m, m, m + pw, m + ph)
        max_alpha = lambda img: max(  # noqa: E731
            img.getchannel("A").crop(region).getdata())
        assert max_alpha(full) >= 250
        assert max_alpha(half) <= 0.6 * max_alpha(full)


class TestAudioLevels:
    def test_silence_stays_at_minimum(self):
        lv = AudioLevels()
        lv.update(b"\x00\x00" * 16000)
        assert lv.levels() == [BAR_MIN_H] * BAR_COUNT

    def test_loud_tone_rises(self):
        lv = AudioLevels()
        lv.update(sine())
        assert max(lv.levels()) > BAR_MIN_H * 2

    def test_release_decays_after_sound_stops(self):
        lv = AudioLevels()
        lv.update(sine())
        peak = max(lv.levels())
        for _ in range(30):
            lv.update(None)
        after = max(lv.levels())
        assert BAR_MIN_H <= after < peak

    def test_short_clip_only_lifts_right_bars(self):
        lv = AudioLevels()
        lv.update(sine(0.2))  # fewer chunks than bars
        levels = lv.levels()
        assert levels[0] == BAR_MIN_H      # left (oldest) bars untouched
        assert levels[-1] > BAR_MIN_H      # newest audio on the right


class TestFluidOverlayFallback:
    def test_falls_back_to_notify_when_display_unavailable(self, monkeypatch):
        import fluidvoice.overlay as ov
        from fluidvoice.preview import NotifyPreview

        def boom(*a, **k):
            raise OSError("no display")

        monkeypatch.setattr("Xlib.display.Display", boom)
        shown: list[str] = []
        monkeypatch.setattr(NotifyPreview, "show",
                            lambda self, t: shown.append(t))
        o = ov.FluidOverlay()
        assert not o.using_overlay
        o.show("hello")
        assert shown == ["hello"]
        o.start()               # no-op without a display
        o.set_state("processing")
        o.close()               # must not raise


class TestConfirmState:
    def test_confirmation_pill_text(self):
        from fluidvoice.overlay import confirmation_pill_text
        text = confirmation_pill_text("ls -la", "list files")
        assert text.startswith("$ ls -la")
        assert "list files" in text
        assert "Esc" in text
        assert "hotkey" in text

    def test_confirmation_pill_text_without_purpose(self):
        from fluidvoice.overlay import confirmation_pill_text
        text = confirmation_pill_text("pwd")
        assert text == "$ pwd\nhotkey = run · Esc = cancel"

    def test_headless_set_state_records_and_validates(self, monkeypatch):
        import fluidvoice.overlay as ov

        def boom(*a, **k):
            raise OSError("no display")

        monkeypatch.setattr("Xlib.display.Display", boom)
        o = ov.FluidOverlay()
        assert o.using_overlay is False
        o.set_state("confirm")
        assert o._state == "confirm"
        with pytest.raises(ValueError):
            o.set_state("nonsense")
        o.close()  # fallback path, must not crash


class TestConfig:
    def test_default_preview_mode_is_auto(self):
        from fluidvoice.config import DEFAULTS
        assert DEFAULTS["recording"]["preview_mode"] == "auto"


class TestModeAccents:
    """Upstream OverlayMode.notchColor parity: dictate white, rewrite blue,
    command red - with per-state labels."""

    def test_accent_table_matches_upstream(self):
        from fluidvoice.overlay import MODE_ACCENTS, state_label
        assert MODE_ACCENTS["dictate"] == (255, 255, 255)
        assert MODE_ACCENTS["rewrite"] != MODE_ACCENTS["dictate"]
        assert MODE_ACCENTS["command"][0] > 200  # red-dominant
        assert state_label("dictate", "processing") == "Transcribing"
        assert state_label("rewrite", "processing") == "Thinking"
        assert state_label("command", "recording") == "Listening..."
        assert state_label("command", "confirm") == "Command"

    def test_command_renders_red_label_white_dictate(self):
        r = PillRenderer()
        img, _ = r.render([BAR_MAX_H] * BAR_COUNT, None, mode="command",
                          state="recording")
        # find a reddish pixel (R >> G,B)
        reds = sum(1 for x in range(0, img.width, 2)
                   for y in range(0, img.height, 2)
                   if (lambda p: p[3] > 200 and p[0] > 200 and p[1] < 140)
                   (img.getpixel((x, y))))
        assert reds > 5
        white, _ = r.render([BAR_MAX_H] * BAR_COUNT, None, mode="dictate",
                            state="recording")
        assert img.tobytes() != white.tobytes()

    def test_label_changes_pill_width(self):
        r = PillRenderer(size="pill")
        w1, _, _ = r.inner_size(None, "Dictate")
        w2, _, _ = r.inner_size(None, "Transcribing")
        assert w2 > w1

    def test_overlay_set_mode_validates(self, monkeypatch):
        import fluidvoice.overlay as ov

        def boom(*a, **k):
            raise OSError("no display")

        monkeypatch.setattr("Xlib.display.Display", boom)
        o = ov.FluidOverlay()
        o.set_mode("command")
        assert o._mode == "command"
        with pytest.raises(ValueError):
            o.set_mode("bogus")
        o.close()


class TestCommandPanel:
    """NotchCommandOutputExpandedView port: structured conversation feed."""

    def _renderer(self):
        from fluidvoice.overlay import CommandPanelRenderer
        return CommandPanelRenderer()

    def test_entries_shrink_panelless_than_cap(self):
        from fluidvoice.overlay import PANEL_MAX_ENTRIES
        r = self._renderer()
        r.set_entries([{"kind": "user", "text": f"step {i}"} for i in range(20)])
        assert len(r.entries) == PANEL_MAX_ENTRIES

    def test_panel_is_wide_and_tall_enough_for_entries(self):
        r = self._renderer()
        r.set_entries([{"kind": "user", "text": "list big files"},
                       {"kind": "proposal", "text": "du -a . | sort -n | tail",
                        "sub": "find the biggest entries"},
                       {"kind": "ok", "text": "$ du -a . · exit 0"}])
        w, h, radius = r.inner_size()
        assert w == 380          # upstream panel width
        assert h >= 120
        assert radius == 16      # upstream corner radius

    def test_render_draws_accent_and_role_marks(self):
        r = self._renderer()
        r.set_entries([{"kind": "user", "text": "check disk usage"},
                       {"kind": "proposal", "text": "df -h",
                        "sub": "show free space"},
                       {"kind": "ok", "text": "$ df -h · exit 0"}])
        r.set_awaiting("run: command key · Esc")
        img, (w, h) = r.render(None, state="confirm")
        assert (w, h) == r.measure()
        reds = sum(1 for x in range(0, img.width, 3)
                   for y in range(0, img.height, 3)
                   if (lambda p: p[3] > 200 and p[0] > 200 and p[1] < 140)
                   (img.getpixel((x, y))))
        assert reds > 5          # "$" marks + dot + hint in command red

    def test_headless_panel_update_close(self, monkeypatch):
        import fluidvoice.overlay as ov

        def boom(*a, **k):
            raise OSError("no display")

        monkeypatch.setattr("Xlib.display.Display", boom)
        p = ov.CommandPanel()
        assert p.using_overlay is False
        p.update([{"kind": "user", "text": "hi"}], status="Working...")
        p.close()


class TestSendBadge:
    """Upstream SpokenSendIndicator, simplified to a pill status chip."""

    def test_badge_widens_pill_and_paints_accent_text(self):
        r = PillRenderer()
        w0, h0, _ = r.inner_size(None, "Transcribing")
        w1, h1, _ = r.inner_size(None, "Transcribing", "⏎ sending…")
        assert w1 > w0
        img, _ = r.render([BAR_MIN_H] * BAR_COUNT, None, mode="dictate",
                          state="processing", badge="⏎ sending…")
        # the badge row is bright text on black somewhere right of center
        strip = img.crop((img.width // 2, 0, img.width, img.height))
        assert bright_pixels(strip) > 5

    def test_overlay_set_badge_updates(self, monkeypatch):
        import fluidvoice.overlay as ov

        def boom(*a, **k):
            raise OSError("no display")

        monkeypatch.setattr("Xlib.display.Display", boom)
        o = ov.FluidOverlay()
        o.set_badge("⏎ sending…")
        assert o._badge == "⏎ sending…"
        o.set_badge(None)
        assert o._badge is None
        o.close()
