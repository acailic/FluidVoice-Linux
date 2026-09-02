"""Live X11 integration: real hotkey grab + synthetic keypress, and the
overlay window rendering (pixel-verified like the manual proof)."""
import os
import subprocess
import time

import pytest

from fluidvoice import control

# `desktop` layer: these verify against the LIVE interactive session (real
# key grabs, real screen pixels) and can flake while the machine is in use.
# Deterministic default runs exclude them:  pytest -m "not desktop"
pytestmark = [pytest.mark.integration, pytest.mark.desktop]


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
        # may hold that grab on a live session). Retry: a previous test
        # daemon's X connection can take a moment to release the grab.
        recording = False
        for _ in range(3):
            subprocess.run(["xdotool", "key", "F9"], check=True, timeout=5)
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                if control.request("status")["recording"]:
                    recording = True
                    break
                time.sleep(0.15)
            if recording:
                break
        assert recording, "F9 grab did not fire within 3 attempts"
        control.request("cancel")
        assert control.request("status")["recording"] is False

    def test_escape_cancels_recording(self, daemon_with_hotkey):
        # macOS parity: Escape while dictating discards it (the grab exists
        # only during recording, so idle Escape is never swallowed).
        # Retry like above: a previous test daemon may still hold the grab.
        recording = False
        for _ in range(3):
            subprocess.run(["xdotool", "key", "F9"], check=True, timeout=5)
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                if control.request("status")["recording"]:
                    recording = True
                    break
                time.sleep(0.15)
            if recording:
                break
        assert recording, "F9 grab did not fire within 3 attempts"
        time.sleep(0.3)  # let the poll loop establish the Escape grab
        subprocess.run(["xdotool", "key", "Escape"], check=True, timeout=5)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            status = control.request("status")
            if not status["recording"]:
                break
            time.sleep(0.15)
        status = control.request("status")
        assert status["recording"] is False
        assert status["ok"] is True  # daemon healthy after the cancel

    def test_daemon_survives_rapid_toggles(self, daemon_process):
        for _ in range(5):
            control.request("toggle")
            time.sleep(0.05)
        control.request("cancel")
        time.sleep(0.3)
        assert control.request("status")["ok"]


@requires_x11
class TestOverlayLive:
    def test_pill_overlay_renders_text_pixels(self):
        from PIL import Image
        from fluidvoice.overlay import BOTTOM_OFFSET, PILL_H, FluidOverlay
        overlay = FluidOverlay()
        assert overlay.using_overlay, "expected the X11 pill overlay on this display"
        try:
            overlay.start()
            overlay.show("INTEGRATION TEST 12345")
            time.sleep(0.8)
            geom = subprocess.run(["xdotool", "getdisplaygeometry"],
                                  capture_output=True, text=True, timeout=5)
            w, h = map(int, geom.stdout.split())
            shot = "/tmp/fv-overlay-itest.png"
            subprocess.run(["import", "-window", "root", shot], timeout=10)
            img = Image.open(shot).convert("L")
            # the pill floats bottom-center, BOTTOM_OFFSET above the screen edge
            cy = h - BOTTOM_OFFSET - PILL_H // 2
            dark = sum(1 for dx in range(-80, 80, 4)
                       if img.getpixel((w // 2 + dx, cy)) < 60)
            light = sum(1 for x in range(w // 2 - 260, w // 2 + 260, 3)
                        for y in range(cy - 60, cy + 20, 3)
                        if img.getpixel((x, y)) > 150)
            assert dark > 20, "pill (dark band) not visible at bottom center"
            assert light > 20, "no bright text/bar pixels inside the pill"
        finally:
            overlay.close()
