"""Live X11 integration: real hotkey grab + synthetic keypress, and the
overlay window rendering (pixel-verified like the manual proof)."""
import os
import subprocess
import time

import pytest

from fluidvoice import control

pytestmark = pytest.mark.integration


def _requires_x11():
    has_display = bool(os.environ.get("DISPLAY"))
    has_xdotool = subprocess.run(["which", "xdotool"],
                                 capture_output=True).returncode == 0
    return pytest.mark.skipif(not (has_display and has_xdotool),
                              reason="requires DISPLAY and xdotool")


requires_x11 = _requires_x11()


@requires_x11
class TestHotkeyLive:
    def test_synthetic_hotkey_toggles_recording(self, daemon_with_hotkey):
        # TEST_CONFIG grabs F9 (never Right_Control: the user's own daemon
        # may hold that grab on a live session).
        subprocess.run(["xdotool", "key", "F9"], check=True, timeout=5)
        time.sleep(1.2)
        status = control.request("status")
        assert status["recording"] is True
        control.request("cancel")
        assert control.request("status")["recording"] is False

    def test_daemon_survives_rapid_toggles(self, daemon_process):
        for _ in range(5):
            control.request("toggle")
            time.sleep(0.05)
        control.request("cancel")
        time.sleep(0.3)
        assert control.request("status")["ok"]


@requires_x11
class TestOverlayLive:
    def test_overlay_renders_text_pixels(self):
        from PIL import Image
        from fluidvoice.preview import X11OverlayPreview
        overlay = X11OverlayPreview()
        assert overlay.using_overlay, "expected the X11 overlay on this display"
        try:
            overlay.show("INTEGRATION TEST 12345")
            time.sleep(0.6)
            geom = subprocess.run(["xdotool", "getdisplaygeometry"],
                                  capture_output=True, text=True, timeout=5)
            w, _h = map(int, geom.stdout.split())
            x0 = (w - 720) // 2
            shot = "/tmp/fv-overlay-itest.png"
            subprocess.run(["import", "-window", "root", shot], timeout=10)
            img = Image.open(shot).convert("L")
            dark = sum(1 for y in range(24, 78) if img.getpixel((x0 + 360, y)) < 60)
            light = sum(1 for x in range(x0, x0 + 720, 4) for y in range(24, 78, 3)
                        if img.getpixel((x, y)) > 150)
            assert dark > 30, "overlay window (dark band) not visible"
            assert light > 20, "no bright text pixels inside the overlay"
        finally:
            overlay.close()
