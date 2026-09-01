from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from fluidvoice import history
from fluidvoice.audio_utils import duration_seconds, is_silent, wav_stats


def write_wav(path: Path, seconds: float, *, loud: bool, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for i in range(int(rate * seconds)):
            v = int(9000 * math.sin(2 * math.pi * 300 * i / rate)) if loud else 0
            wf.writeframes(struct.pack("<h", v))
    return path


class TestAudioUtils:
    def test_loud_audio_not_silent(self, tmp_path):
        wav = write_wav(tmp_path / "loud.wav", 1.0, loud=True)
        assert not is_silent(str(wav))
        stats = wav_stats(str(wav))
        assert stats.rms > 0.01 and stats.peak > 0.1

    def test_digital_silence_detected(self, tmp_path):
        wav = write_wav(tmp_path / "silent.wav", 2.0, loud=False)
        assert is_silent(str(wav))

    def test_duration(self, tmp_path):
        wav = write_wav(tmp_path / "d.wav", 1.5, loud=True)
        assert abs(duration_seconds(str(wav)) - 1.5) < 0.01

    def test_empty_file_stats(self, tmp_path):
        wav = write_wav(tmp_path / "e.wav", 0.0, loud=False)
        stats = wav_stats(str(wav))
        assert stats.peak == 0.0 and stats.rms == 0.0


class TestHistory:
    def test_append_and_tail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        history.append({"ts": 1, "text": "first"})
        history.append({"ts": 2, "text": "second"})
        entries = history.tail(10)
        assert [e["text"] for e in entries] == ["first", "second"]

    def test_tail_n(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        for i in range(5):
            history.append({"ts": i, "text": f"t{i}"})
        assert [e["text"] for e in history.tail(2)] == ["t3", "t4"]

    def test_corrupt_lines_skipped(self, tmp_path, monkeypatch):
        f = tmp_path / "h.jsonl"
        f.write_text('{"ts": 1, "text": "ok"}\nnot json\n')
        monkeypatch.setattr(history.paths, "history_file", lambda: f)
        assert [e["text"] for e in history.tail()] == ["ok"]

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "nope.jsonl")
        assert history.tail() == []

    def test_audio_saved_when_requested(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        monkeypatch.setattr(history.paths, "audio_dir", lambda: tmp_path / "audio")
        src = write_wav(tmp_path / "src.wav", 0.5, loud=True)
        history.append({"ts": 1, "text": "with audio"}, audio_src=src,
                       keep_audio=True, budget_gb=1.0)
        saved = list((tmp_path / "audio").glob("*.wav"))
        assert len(saved) == 1

    def test_audio_budget_prunes_oldest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        monkeypatch.setattr(history.paths, "audio_dir", lambda: tmp_path / "audio")
        adir = tmp_path / "audio"
        adir.mkdir()
        import os
        import time as _time
        old = adir / "old.wav"
        new = adir / "new.wav"
        old.write_bytes(b"x" * 1000)
        new.write_bytes(b"y" * 1000)
        os.utime(old, (_time.time() - 100, _time.time() - 100))
        history._enforce_budget(adir, budget_gb=1000 / 1024 ** 3)  # ~1KB budget
        assert not old.exists()
        assert new.exists()
