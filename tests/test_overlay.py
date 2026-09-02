"""Mac-style pill overlay renderer tests (headless - no X11 needed)."""
from __future__ import annotations

import math
import struct

from fluidvoice.overlay import (BAR_COUNT, BAR_MAX_H, BAR_MIN_H, PILL_H,
                                PILL_RADIUS, TEXT_RADIUS, AudioLevels,
                                PillRenderer, head_truncate)


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
        r = PillRenderer()
        w, h, radius = r.inner_size(None)
        assert h == PILL_H
        assert radius == PILL_RADIUS  # stadium: height / 2
        assert w >= 100               # icon + waveform + label fit

    def test_text_grows_pill_and_switches_radius(self):
        r = PillRenderer()
        w0, h0, _ = r.inner_size(None)
        w1, h1, radius = r.inner_size("hello world")
        assert h1 > h0
        assert radius == TEXT_RADIUS
        assert w1 >= w0

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


class TestConfig:
    def test_default_preview_mode_is_auto(self):
        from fluidvoice.config import DEFAULTS
        assert DEFAULTS["recording"]["preview_mode"] == "auto"
