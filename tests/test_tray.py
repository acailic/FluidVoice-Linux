"""Tray icon tests (headless - no D-Bus session needed)."""
from __future__ import annotations

from fluidvoice.tray import TRAY_SIZE, TrayIcon, render_pixmaps


class TestPixmaps:
    def test_both_variants_sized(self):
        pm = render_pixmaps()
        assert set(pm) == {"idle", "recording"}
        for w, h, data in pm.values():
            assert w == h == TRAY_SIZE
            assert len(data) == w * h * 4

    def test_recording_badge_changes_pixels(self):
        pm = render_pixmaps()
        assert pm["idle"][2] != pm["recording"][2]

    def test_argb32_byte_order(self):
        # SNI pixmaps are ARGB32 big-endian: the rounded corner pixel must
        # lead with alpha ~= 0 and carry no RGB under it
        w, h, data = render_pixmaps(size=32)["idle"]
        assert data[0] < 40
        assert data[1] == data[2] == data[3] == 0

    def test_missing_icon_falls_back_to_drawn_glyph(self, tmp_path):
        w, h, data = render_pixmaps(tmp_path / "nope.png")["idle"]
        assert len(data) == TRAY_SIZE * TRAY_SIZE * 4
        i = (h // 2 * w + w // 2) * 4
        assert data[i] > 200  # opaque glyph at the center


class TestFallback:
    def test_start_fails_cleanly_without_dbus(self, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def no_dbus(name, *args, **kwargs):
            if name.split(".")[0] in ("dbus", "gi"):
                raise ImportError("no dbus here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_dbus)
        t = TrayIcon()
        assert t.start() is False
        t.set_recording(True)  # inactive paths must not raise
        t.stop()

    def test_config_default_enabled(self):
        from fluidvoice.config import DEFAULTS
        assert DEFAULTS["general"]["tray_enabled"] is True
