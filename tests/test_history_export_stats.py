"""History ZIP export + today-usage stats (pure functions, local files only)."""
from __future__ import annotations

import json
import math
import struct
import time
import wave
import zipfile
from pathlib import Path

from fluidvoice import history


def write_wav(path: Path, seconds: float, *, loud: bool, rate: int = 16000) -> Path:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for i in range(int(rate * seconds)):
            v = int(9000 * math.sin(2 * math.pi * 300 * i / rate)) if loud else 0
            wf.writeframes(struct.pack("<h", v))
    return path


def midnight_of(now: float) -> float:
    return time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))


class TestExportZip:
    def _patch(self, monkeypatch, tmp_path) -> Path:
        adir = tmp_path / "audio"
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        monkeypatch.setattr(history.paths, "audio_dir", lambda: adir)
        return adir

    def _write_entries(self, tmp_path, entries) -> Path:
        hpath = tmp_path / "h.jsonl"
        hpath.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                 for e in entries), encoding="utf-8")
        return hpath

    def test_roundtrip(self, tmp_path, monkeypatch):
        adir = self._patch(monkeypatch, tmp_path)
        adir.mkdir()
        a = write_wav(adir / "a.wav", 0.1, loud=True)
        b = write_wav(adir / "b.wav", 0.2, loud=False)
        entries = [
            {"ts": 1, "text": "with audio", "audio": str(a)},
            {"ts": 2, "text": "no audio here"},  # no audio key at all
            {"ts": 3, "text": "also audio", "audio": str(b)},
        ]
        self._write_entries(tmp_path, entries)
        target = tmp_path / "out.zip"
        assert history.export_zip(target) == 3
        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            assert "history.jsonl" in names
            assert "audio/a.wav" in names and "audio/b.wav" in names
            assert [json.loads(l) for l in
                    zf.read("history.jsonl").decode().splitlines()] == entries
            assert zf.read("audio/a.wav") == a.read_bytes()
            assert zf.read("audio/b.wav") == b.read_bytes()

    def test_missing_audio_skipped_with_note(self, tmp_path, monkeypatch):
        adir = self._patch(monkeypatch, tmp_path)
        adir.mkdir()
        entries = [{"ts": 1, "text": "gone", "audio": str(adir / "nope.wav")}]
        self._write_entries(tmp_path, entries)
        notes: list[str] = []
        n = history.export_zip(tmp_path / "out.zip", on_note=notes.append)
        assert n == 1  # the entry itself still counts
        with zipfile.ZipFile(tmp_path / "out.zip") as zf:
            assert zf.namelist() == ["history.jsonl"]
            assert json.loads(zf.read("history.jsonl")) == entries[0]
        assert any("missing" in m for m in notes)
        assert any("nope.wav" in m for m in notes)

    def test_path_traversal_refused(self, tmp_path, monkeypatch):
        adir = self._patch(monkeypatch, tmp_path)
        adir.mkdir()
        outside = write_wav(tmp_path / "outside.wav", 0.1, loud=True)
        entries = [
            {"ts": 1, "text": "absolute escape", "audio": str(outside)},
            {"ts": 2, "text": "relative escape",
             "audio": str(adir / ".." / ".." / "evil.wav")},
        ]
        self._write_entries(tmp_path, entries)
        notes: list[str] = []
        n = history.export_zip(tmp_path / "out.zip", on_note=notes.append)
        assert n == 2  # entries exported regardless
        with zipfile.ZipFile(tmp_path / "out.zip") as zf:
            assert zf.namelist() == ["history.jsonl"]
            lines = [json.loads(l)
                     for l in zf.read("history.jsonl").decode().splitlines()]
            assert len(lines) == 2
        assert len(notes) == 2 and all("refused" in m for m in notes)

    def test_empty_history(self, tmp_path, monkeypatch):
        self._patch(monkeypatch, tmp_path)
        target = tmp_path / "out.zip"
        assert history.export_zip(target) == 0
        with zipfile.ZipFile(target) as zf:
            assert zf.namelist() == ["history.jsonl"]
            assert zf.read("history.jsonl") == b""

    def test_duplicate_arcnames_deduped(self, tmp_path, monkeypatch):
        adir = self._patch(monkeypatch, tmp_path)
        adir.mkdir()
        a = write_wav(adir / "same.wav", 0.1, loud=True)
        entries = [{"ts": 1, "text": "one", "audio": str(a)},
                   {"ts": 2, "text": "two", "audio": str(a)}]
        self._write_entries(tmp_path, entries)
        assert history.export_zip(tmp_path / "out.zip") == 2
        with zipfile.ZipFile(tmp_path / "out.zip") as zf:
            assert zf.namelist().count("audio/same.wav") == 1

    def test_uses_read_all_not_tail(self, tmp_path, monkeypatch):
        """Export must see the whole file, not tail()'s 128 KB window."""
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        monkeypatch.setattr(history.paths, "audio_dir",
                            lambda: tmp_path / "audio")
        entries = [{"ts": i, "text": f"e{i}"} for i in range(50)]
        self._write_entries(tmp_path, entries)
        monkeypatch.setattr(history, "_TAIL_WINDOW", 256)
        target = tmp_path / "out.zip"
        assert history.export_zip(target) == 50
        with zipfile.ZipFile(target) as zf:
            lines = zf.read("history.jsonl").decode().splitlines()
            assert len(lines) == 50 and json.loads(lines[0])["ts"] == 0


class TestTodayStats:
    NOW = 1756812345.0  # fixed; midnight derived with the same formula

    def test_midnight_boundary_inclusive(self):
        midnight = midnight_of(self.NOW)
        entries = [
            {"ts": midnight - 1, "text": "yesterday", "duration_s": 9.0},
            {"ts": midnight, "text": "just past", "duration_s": 1.0},
            {"ts": midnight + 60, "text": "today", "duration_s": 2.0},
        ]
        st = history.today_stats(entries, now=self.NOW)
        assert st == {"dictations": 2, "seconds": 3.0, "words": 3}

    def test_empty(self):
        assert history.today_stats([], now=self.NOW) == \
            {"dictations": 0, "seconds": 0.0, "words": 0}

    def test_missing_ts_not_today(self):
        midnight = midnight_of(self.NOW)
        st = history.today_stats(
            [{"text": "no ts", "duration_s": 5.0},
             {"ts": midnight, "raw": "counts"}], now=self.NOW)
        assert st["dictations"] == 1

    def test_word_and_duration_counting(self):
        midnight = midnight_of(self.NOW)
        entries = [
            {"ts": midnight + 10, "text": "hello world", "duration_s": 5.5},
            {"ts": midnight + 20, "raw": "one two three four",
             "duration_s": 1.0},
        ]
        st = history.today_stats(entries, now=self.NOW)
        assert st == {"dictations": 2, "seconds": 6.5, "words": 6}

    def test_text_wins_over_raw(self):
        midnight = midnight_of(self.NOW)
        st = history.today_stats(
            [{"ts": midnight + 5, "text": "final text",
              "raw": "raw words ignored here", "duration_s": 1.0}],
            now=self.NOW)
        assert st["words"] == 2

    def test_missing_duration_counts_zero(self):
        midnight = midnight_of(self.NOW)
        st = history.today_stats(
            [{"ts": midnight, "text": "hi"}], now=self.NOW)
        assert st == {"dictations": 1, "seconds": 0.0, "words": 1}

    def test_format_today(self):
        assert history.format_today(
            {"dictations": 2, "seconds": 75.4, "words": 6}) == \
            "2 dictations, 1:15 minutes, 6 words"
        assert history.format_today(
            {"dictations": 1, "seconds": 45.0, "words": 3}) == \
            "1 dictations, 0:45 minutes, 3 words"

    def test_read_all_counts_since_midnight(self, tmp_path, monkeypatch):
        """read_all() + today_stats() over a real file (the daemon path)."""
        monkeypatch.setattr(history.paths, "history_file",
                            lambda: tmp_path / "h.jsonl")
        now = time.time()
        (tmp_path / "h.jsonl").write_text(
            json.dumps({"ts": now, "text": "now now", "duration_s": 2.0})
            + "\n" + json.dumps({"ts": now - 86400 * 2, "text": "old",
                                 "duration_s": 99.0}) + "\n", encoding="utf-8")
        st = history.today_stats(history.read_all())
        assert st["dictations"] == 1
        assert st["seconds"] == 2.0
        assert st["words"] == 2
