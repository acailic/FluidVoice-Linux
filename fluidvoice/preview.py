"""Live streaming preview: rolling transcription while recording.

The recorder captures headerless raw PCM; PreviewEngine periodically wraps
the accumulated bytes in a WAV (in memory) and transcribes the growing
prefix through the faster-whisper model. Partial text goes to a pluggable
display: an X11 override-redirect overlay window (no focus stealing) or a
replaceable desktop notification (works everywhere).
"""
from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Callable

from .audio_utils import raw_to_wav_bytes


class PreviewEngine:
    """Background thread that turns a growing raw PCM file into partial text."""

    def __init__(self, raw_path: Path, transcriber: Callable[[bytes], str],
                 on_text: Callable[[str], None], *,
                 sample_rate: int = 16000, interval: float = 1.2,
                 min_audio: float = 1.0, char_limit: int = 160):
        self.raw_path = raw_path
        self.transcriber = transcriber
        self.on_text = on_text
        self.sample_rate = sample_rate
        self.interval = interval
        self.min_bytes = int(min_audio * sample_rate * 2)
        self.char_limit = char_limit
        self._stop = threading.Event()
        self._busy = False
        self._thread: threading.Thread | None = None
        self.last_text = ""

    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="fluidvoice-preview",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            if self._busy:  # previous pass still transcribing - skip this tick
                continue
            try:
                raw = self._read_new()
            except OSError:
                continue
            if raw is None or len(raw) < self.min_bytes:
                continue
            self._busy = True
            try:
                wav = raw_to_wav_bytes(raw, self.sample_rate)
                text = self.transcriber(wav).strip()
                if text and text != self.last_text:
                    self.last_text = text
                    self._emit(text)
            except Exception:
                pass  # preview is best-effort; the final pass is authoritative
            finally:
                self._busy = False

    def _read_new(self) -> bytes | None:
        try:
            with open(self.raw_path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            return None

    def _emit(self, text: str) -> None:
        shown = text if len(text) <= self.char_limit else "…" + text[-self.char_limit:]
        try:
            self.on_text(shown)
        except Exception:
            pass


def faster_whisper_transcriber(model, language: str | None) -> Callable[[bytes], str]:
    """Build a bytes->text transcriber from a loaded faster-whisper model."""
    lang = None if language in (None, "", "auto") else language

    def transcribe(wav_bytes: bytes) -> str:
        segments, _ = model.transcribe(io.BytesIO(wav_bytes), language=lang,
                                       beam_size=1, condition_on_previous_text=False,
                                       without_timestamps=True)
        return " ".join(s.text.strip() for s in segments if s.text.strip())
    return transcribe


# ---------------------------------------------------------------------------
# Displays
# ---------------------------------------------------------------------------

class NotifyPreview:
    """Replaceable desktop notification (notify-send -r reuses one bubble)."""

    def __init__(self, timeout_ms: int = 2000):
        import shutil
        self.supported = bool(shutil.which("notify-send"))
        self.timeout_ms = timeout_ms
        self._id: int | None = None

    def show(self, text: str) -> None:
        if not self.supported:
            return
        import subprocess
        args = ["notify-send", "-a", "FluidVoice", "-t", str(self.timeout_ms)]
        if self._id is not None:
            args += ["-r", str(self._id), "-e"]
        args += [f"● {text}"]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=3)
            out = (proc.stdout or "").strip()
            if out.isdigit():
                self._id = int(out)
        except Exception:
            pass

    def close(self) -> None:
        if self._id is not None and self.supported:
            import subprocess
            try:
                subprocess.run(["notify-send", "-a", "FluidVoice", "-r",
                                str(self._id), "-t", "1", " "], timeout=3)
            except Exception:
                pass
            self._id = None


class X11OverlayPreview:
    """Small always-on-top, never-focusable text window at the top of the
    screen (override-redirect). Falls back to notifications on any error."""

    WIDTH, HEIGHT, MAX_CHARS = 720, 54, 80

    def __init__(self, display_name: str | None = None):
        self.fallback = NotifyPreview()
        self._d = None
        try:
            from Xlib import X, XK
            from Xlib.display import Display
            self._X = X
            self._d = Display(display_name)
            screen = self._d.screen()
            self._font = self._d.open_font(b"-misc-fixed-medium-r-semicondensed--13-120-75-75-c-60-iso10646-1")
            if not self._font:
                self._font = self._d.open_font(b"fixed")
            self._gc = screen.root.create_gc(
                foreground=self._d.screen().white_pixel,
                background=self._d.screen().black_pixel,
                font=self._font)
            x = (screen.width_in_pixels - self.WIDTH) // 2
            self._win = screen.root.create_window(
                x, 24, self.WIDTH, self.HEIGHT, 1,
                screen.root_depth,
                override_redirect=True,
                event_mask=X.ExposureMask,
                background_pixel=screen.black_pixel,
                border_pixel=screen.white_pixel)
            self._d.sync()
        except Exception:
            self._close_display()
            self._d = None  # fallback mode

    @property
    def using_overlay(self) -> bool:
        return self._d is not None

    def show(self, text: str) -> None:
        if self._d is None:
            self.fallback.show(text)
            return
        try:
            X = self._X
            self._win.map()
            # brief exposure settle, then draw (double-buffered by clear+draw)
            while self._d.pending_events() > 0:
                self._d.next_event()  # drain exposes
            self._win.clear_area(x=0, y=0, width=self.WIDTH, height=self.HEIGHT)
            shown = text if len(text) <= self.MAX_CHARS else text[:self.MAX_CHARS - 1] + "…"
            self._win.draw_text(self._gc, 12, self.HEIGHT // 2 + 5, shown.encode("utf-8"))
            self._d.sync()
        except Exception:
            self._close_display()
            self._d = None
            self.fallback.show(text)

    def close(self) -> None:
        if self._d is not None:
            try:
                self._win.unmap()
                self._d.sync()
            except Exception:
                pass
            self._close_display()
        self.fallback.close()

    def _close_display(self) -> None:
        if self._d is not None:
            try:
                self._d.close()
            except Exception:
                pass
            self._d = None
