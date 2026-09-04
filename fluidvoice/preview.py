"""Live streaming preview: rolling transcription while recording.

The recorder captures headerless raw PCM; PreviewEngine periodically wraps
the accumulated bytes in a WAV (in memory) and transcribes the growing
prefix through the faster-whisper model. Partial text goes to a pluggable
display: the Mac-style pill overlay (overlay.FluidOverlay) or a replaceable
desktop notification (works everywhere).
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

    def start(self) -> None:  # overlay parity: no window to map
        pass

    def set_state(self, state: str) -> None:  # no processing visual
        pass

    def show(self, text: str) -> None:
        if not self.supported:
            return
        import subprocess
        args = ["notify-send", "-a", "SayItErmano", "-t", str(self.timeout_ms)]
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
                subprocess.run(["notify-send", "-a", "SayItErmano", "-r",
                                str(self._id), "-t", "1", " "], timeout=3)
            except Exception:
                pass
            self._id = None


# The X11 pill overlay (Mac-style BottomOverlayView port) lives in
# .overlay.FluidOverlay; this module keeps the engine + notification fallback.
