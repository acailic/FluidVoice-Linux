"""Daemon state machine + DictationPipeline, tested with stubs (no X11/audio/GPU)."""
from __future__ import annotations

import copy
import math
import struct
import time
import wave
from pathlib import Path

import pytest

from fluidvoice import daemon as dm
from fluidvoice.ai.client import AIError
from fluidvoice.config import DEFAULTS
from fluidvoice.insertion import InsertError
from fluidvoice.recorder import RecorderError


def make_wav(path: Path, seconds: float = 1.0, loud: bool = True, rate: int = 16000) -> Path:
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = int(12000 * math.sin(2 * math.pi * 440 * i / rate)) if loud else 0
            frames += struct.pack("<h", v)
        wf.writeframes(bytes(frames))
    # pad to >200 bytes so the daemon treats it as real audio
    if path.stat().st_size < 200:
        with open(path, "ab") as fh:
            fh.write(b"\0" * 300)
    return path


class StubRecorder:
    def __init__(self, fail_start=False):
        self.fail_start = fail_start
        self.path: Path | None = None
        self.started = 0
        self.stopped = 0
        self.cancelled = 0

    def start(self, path):
        if self.fail_start:
            raise RecorderError("no recorder found")
        self.path = make_wav(path)
        self.started += 1

    def stop(self):
        self.stopped += 1
        return self.path

    def cancel(self):
        self.cancelled += 1
        self.stopped += 1
        self.path = None

    def elapsed(self):
        return 0.0


class StubBackend:
    name = "stub"

    def __init__(self, text="hello world", error: Exception | None = None):
        self.text = text
        self.error = error
        self.calls: list = []

    def transcribe(self, wav, language=None):
        self.calls.append((str(wav), language))
        if self.error:
            raise self.error
        return {"text": self.text, "language": "en", "duration": 1.0}


@pytest.fixture()
def cfg():
    return copy.deepcopy(DEFAULTS)


@pytest.fixture()
def quiet_ui(monkeypatch):
    """Silence real notifications/sounds and record them."""
    calls = {"notify": [], "sound": []}

    def fake_notify(title, body="", timeout_ms=2500, enabled=True):
        if enabled:
            calls["notify"].append((title, body))

    def fake_sound(which, volume=1.0, enabled=True):
        if enabled:
            calls["sound"].append(which)

    monkeypatch.setattr(dm.ui, "notify", fake_notify)
    monkeypatch.setattr(dm.ui, "play_sound", fake_sound)
    monkeypatch.setattr(dm.insertion, "active_window_class", lambda: "TestApp")
    return calls


# ---------------------------------------------------------------------------
# DictationPipeline
# ---------------------------------------------------------------------------

class TestPipeline:
    def _run(self, tmp_path, cfg, backend, **kw):
        wav = make_wav(tmp_path / "utt.wav")
        pipe = dm.DictationPipeline(cfg, backend, **kw)
        return pipe, pipe.run(wav, "TestApp")

    def test_happy_path(self, tmp_path, cfg, quiet_ui):
        inserted, history = [], []
        pipe, out = self._run(
            tmp_path, cfg, StubBackend("um hello literal comma world"),
            inserter=lambda text, c: (inserted.append(text), "typed")[1],
            history_writer=lambda entry, wav: history.append(entry))
        assert out["strategy"] == "typed"
        assert inserted == ["hello, world"]  # filler removed + punctuation applied
        assert out["ai"] is False
        assert history and history[0]["app"] == "TestApp"
        assert history[0]["backend"] == "stub"
        assert not (tmp_path / "utt.wav").exists()  # temp cleaned up

    def test_empty_transcription(self, tmp_path, cfg, quiet_ui):
        inserted = []
        _, out = self._run(tmp_path, cfg, StubBackend("  "),
                           inserter=lambda t, c: inserted.append(t))
        assert out is None and inserted == []

    def test_backend_error_notifies(self, tmp_path, cfg, quiet_ui):
        _, out = self._run(tmp_path, cfg, StubBackend(error=RuntimeError("cuda blew up")),
                           inserter=lambda t, c: "typed")
        assert out is None
        assert any("Transcription failed" in (t + b) for t, b in quiet_ui["notify"])

    def test_silence_gate(self, tmp_path, cfg, quiet_ui):
        cfg["recording"]["skip_silent"] = True
        inserted = []
        wav = make_wav(tmp_path / "silence.wav", seconds=2.0, loud=False)
        pipe = dm.DictationPipeline(cfg, StubBackend("should not run"),
                                    inserter=lambda t, c: inserted.append(t))
        assert pipe.run(wav, None) is None
        assert inserted == []

    def test_loud_audio_passes_silence_gate(self, tmp_path, cfg, quiet_ui):
        cfg["recording"]["skip_silent"] = True
        _, out = self._run(tmp_path, cfg, StubBackend("words"))
        assert out is not None

    def test_ai_polish(self, tmp_path, cfg, quiet_ui):
        cfg["ai"]["enabled"] = True
        _, out = self._run(tmp_path, cfg, StubBackend("rough text"),
                           polisher=lambda t: "Polished!",
                           inserter=lambda t, c: inserted(t))
        assert out["text"] == "Polished!" and out["ai"] is True

    def test_ai_error_falls_back_to_raw(self, tmp_path, cfg, quiet_ui):
        cfg["ai"]["enabled"] = True

        def broken(_):
            raise AIError("ollama down")

        got = []
        _, out = self._run(tmp_path, cfg, StubBackend("raw words"),
                           polisher=broken,
                           inserter=lambda t, c: (got.append(t), "typed")[1])
        assert out["text"] == "raw words" and out["ai"] is False
        assert got == ["raw words"]

    def test_insertion_failure_uses_clipboard_fallback(self, tmp_path, cfg, quiet_ui, monkeypatch):
        fallback = []
        monkeypatch.setattr(dm.insertion, "clipboard_fallback", lambda t: fallback.append(t))

        def broken(_t, _c):
            raise InsertError("no display")

        _, out = self._run(tmp_path, cfg, StubBackend("help me"), inserter=broken)
        assert out["strategy"] == "clipboard-fallback"
        assert fallback == ["help me"]

    def test_history_disabled(self, tmp_path, cfg, quiet_ui):
        cfg["history"]["save"] = False
        writer = []
        _, out = self._run(tmp_path, cfg, StubBackend("x"),
                           history_writer=lambda e, w: writer.append(e))
        assert out is not None and writer == []


def inserted(text):
    """Shared inserter stub: records nothing, reports 'typed'."""
    return "typed"


# ---------------------------------------------------------------------------
# Daemon state machine
# ---------------------------------------------------------------------------

class TestDaemon:
    def make(self, cfg, recorder, backend=None):
        backend = backend or StubBackend("typed text")
        d = dm.Daemon(cfg, recorder=recorder,
                      backend_factory=lambda c: backend,
                      use_hotkey=False, use_sounds=False)
        d.backend = backend  # simulate a successful startup load
        return d

    def wait_done(self, d, timeout=5.0) -> bool:
        """Wait for any in-flight processing thread to finish."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if d._process_thread is None or not d._process_thread.is_alive():
                return not d.busy
            time.sleep(0.02)
        return False

    def test_toggle_cycle(self, cfg, quiet_ui, tmp_path):
        rec = StubRecorder()
        d = self.make(cfg, rec)
        assert d.handle_request({"action": "toggle"})["recording"] is True
        assert rec.started == 1
        assert d.handle_request({"action": "toggle"})["recording"] is False
        assert self.wait_done(d)
        assert d.last_result.get("text") == "typed text"
        assert rec.stopped == 1

    def test_status_action(self, cfg, quiet_ui):
        d = self.make(cfg, StubRecorder())
        resp = d.handle_request({"action": "status"})
        assert resp["ok"] and resp["recording"] is False and resp["backend"] == "stub"

    def test_unknown_action(self, cfg, quiet_ui):
        d = self.make(cfg, StubRecorder())
        resp = d.handle_request({"action": "explode"})
        assert resp["ok"] is False and "unknown action" in resp["error"]

    def test_cancel(self, cfg, quiet_ui):
        rec = StubRecorder()
        d = self.make(cfg, rec)
        d.toggle()
        resp = d.handle_request({"action": "cancel"})
        assert resp["cancelled"] and not d.recording
        assert rec.cancelled == 1
        assert rec.path is None  # temp file discarded

    def test_cancel_when_idle_is_noop(self, cfg, quiet_ui):
        rec = StubRecorder()
        d = self.make(cfg, rec)
        d.cancel()
        assert rec.cancelled == 0

    def test_busy_guard_ignores_toggle(self, cfg, quiet_ui):
        rec = StubRecorder()
        d = self.make(cfg, rec)
        d.busy = True
        assert d.toggle() is False  # did not start recording
        assert rec.started == 0

    def test_recorder_start_failure_notifies(self, cfg, quiet_ui):
        rec = StubRecorder(fail_start=True)
        d = self.make(cfg, rec)
        assert d.toggle() is False
        assert any("Recording failed" in (t + b) for t, b in quiet_ui["notify"])
        assert not d.recording

    def test_watchdog_auto_stops(self, cfg, quiet_ui):
        cfg["recording"]["max_seconds"] = 0.2
        rec = StubRecorder()
        d = self.make(cfg, rec)
        d.toggle()
        assert d.recording
        deadline = time.monotonic() + 5
        while d.recording and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not d.recording
        assert self.wait_done(d)

    def test_shutdown_while_recording_cancels(self, cfg, quiet_ui):
        rec = StubRecorder()
        d = self.make(cfg, rec)
        d.toggle()
        d.shutdown()
        assert rec.cancelled == 1 and not d.recording

    def test_backend_factory_failure_is_lazy(self, cfg, quiet_ui, tmp_path):
        rec = StubRecorder()
        d = dm.Daemon(cfg, recorder=rec,
                      backend_factory=lambda c: (_ for _ in ()).throw(RuntimeError("no model")),
                      use_hotkey=False, use_sounds=False)
        d.toggle()
        d.toggle()
        assert self.wait_done(d)
        assert d.last_result == {}  # nothing typed, error notified
        assert any("Transcription failed" in (t + b) for t, b in quiet_ui["notify"])
