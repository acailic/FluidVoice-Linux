"""Segmented streaming preview (requests/streaming-finalization.md phase 1).

Covers: fixed-window tiling + finalize semantics, the constant per-tick
decode bound (N windows -> N decode calls, each one window of audio - not
O(take) re-decodes), the trailing-silence VAD trigger table, and the
backend-generalized transcriber factory.
"""
from __future__ import annotations

import math
import struct
import time
from pathlib import Path

from fluidvoice.preview import (SegmentedPreviewEngine, join_tail,
                                preview_transcriber, trailing_silence_s)

RATE = 16000
BPS = RATE * 2  # s16 mono bytes per second


def pcm(seconds: float, freq: int = 440, amp: int = 8000) -> bytes:
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / RATE)))
        for i in range(int(seconds * RATE)))


def silence(seconds: float) -> bytes:
    return b"\x00" * int(seconds * RATE) * 2


def fricative(seconds: float) -> bytes:
    """Low-energy high-ZCR wave: unvoiced consonant ("sss") - not silence."""
    return pcm(seconds, freq=6000, amp=120)


class RecordingEngine(SegmentedPreviewEngine):
    """Test seam: record every decode span (start_s, end_s)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.positions: list[tuple[float, float]] = []

    def _decode(self, start_s, end_s, ctx):
        self.positions.append((round(start_s, 3), round(end_s, 3)))
        return super()._decode(start_s, end_s, ctx)


def drive(engine: SegmentedPreviewEngine, raw: Path, total_s: float,
          step_s: float) -> None:
    """Deterministically replay the recording loop: grow the file, tick."""
    data = b""
    t = step_s
    while t <= total_s + 1e-9:
        data += pcm(step_s) if t > 0 else b""
        raw.write_bytes(data)
        engine._tick(data, len(data) / BPS)
        t += step_s


class TestSegmentation:
    def test_commit_windows_tile_stream_exactly(self, tmp_path):
        raw = tmp_path / "take.raw"
        raw.write_bytes(pcm(0.2))
        eng = RecordingEngine(raw, lambda w, c: "word", lambda t: None,
                              interval=1.2, min_audio=0.5, segment_s=2.0)
        drive(eng, raw, total_s=10.0, step_s=0.5)
        commits = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0), (6.0, 8.0), (8.0, 10.0)]
        for span in commits:
            assert span in eng.positions, f"missing commit decode {span}"
        # every commit span decoded exactly once
        for span in commits:
            assert eng.positions.count(span) == 1
        assert len(eng.committed) == 5
        assert eng.stats["commits"] == 5
        assert eng.stats["covered_s"] == 10.0

    def test_constant_decode_cost_not_quadratic(self, tmp_path):
        raw = tmp_path / "long.raw"
        raw.write_bytes(pcm(0.2))
        calls = []

        def counter(wav, ctx):
            calls.append(len(wav))
            return "w"

        eng = SegmentedPreviewEngine(raw, counter, lambda t: None,
                                     interval=1.0, min_audio=0.5, segment_s=2.0)
        ticks = 40
        drive(eng, raw, total_s=float(ticks), step_s=1.0)
        # one window (<= 2 s of audio) per tick, never the whole take again
        assert len(calls) <= ticks + 1
        assert sum(calls) <= (ticks + 1) * BPS * 2
        # a legacy whole-buffer engine would have decoded ticks*(ticks+1)/2
        # audio-seconds by now; assert we are far below that
        assert sum(calls) / BPS < ticks * ticks / 4

    def test_committed_text_monotone_and_stable(self, tmp_path):
        raw = tmp_path / "m.raw"
        raw.write_bytes(pcm(0.2))
        snapshots = []  # (committed tuple as of tick, displayed text)

        def wordy(wav, ctx):
            # window-length-derived text: tail slices differ from commits,
            # like a real decoder re-rendering the live region
            return f"w{int(len(wav) / (BPS * 2))}"

        class Snapshots(SegmentedPreviewEngine):
            def _tick(self, raw, audio_s):
                super()._tick(raw, audio_s)
                snapshots.append((tuple(self.committed), self.last_text))

        eng = Snapshots(raw, wordy, lambda t: None,
                        interval=1.0, min_audio=0.5, segment_s=2.0)
        drive(eng, raw, total_s=8.0, step_s=0.5)
        assert len(eng.committed) == 4  # windows 0, 2, 4, 6 committed once
        # finalized text is stable: once a segment is committed, the display
        # always starts with the full committed prefix from then on
        seen_committed = ()
        for committed, text in snapshots:
            if committed != seen_committed:
                seen_committed = committed
            else:
                prefix = " ".join(t for t in committed if t)
                assert not prefix or text.startswith(prefix)
        assert eng.last_text.startswith(
            " ".join(t for t in eng.committed if t))

    def test_tail_decode_is_newest_slice(self, tmp_path):
        raw = tmp_path / "t.raw"
        raw.write_bytes(pcm(0.2))
        eng = RecordingEngine(raw, lambda w, c: "x", lambda t: None,
                              interval=1.2, min_audio=0.5, segment_s=2.0)
        # single tick at t=1.4: no commit window yet (needs t>=2), tail only
        data = pcm(1.4)
        raw.write_bytes(data)
        eng._tick(data, 1.4)
        assert eng.positions == [(0.0, 1.4)]
        # t=3.0: commit window 0 due first; tail refresh comes on a later tick
        data += pcm(1.6)
        raw.write_bytes(data)
        eng._tick(data, 3.0)
        assert eng.positions[-1] == (0.0, 2.0)
        eng._tick(data, 3.0)  # same stream, no new commit -> tail
        assert eng.positions[-1] == (1.0, 3.0)

    def test_errors_are_swallowed(self, tmp_path):
        raw = tmp_path / "e.raw"
        raw.write_bytes(pcm(0.3))

        def broken(wav, ctx):
            raise RuntimeError("cuda busy")

        eng = SegmentedPreviewEngine(raw, broken, lambda t: None,
                                     interval=0.1, min_audio=0.1)
        eng._tick(pcm(3.0), 3.0)  # must not raise
        eng.stop()


class TestTailDedupe:
    def test_drops_reemitted_overlap(self):
        assert join_tail("hello world", "world again") == "again"

    def test_no_false_drop(self):
        assert join_tail("hello world", "again please") == "again please"

    def test_empty_sides(self):
        assert join_tail("", "tail") == "tail"
        assert join_tail("committed", "") == ""


class TestVad:
    def make_engine(self, raw: Path, texts, fired) -> SegmentedPreviewEngine:
        def fake(wav, ctx):
            seconds = len(wav) / BPS
            return texts(seconds)

        return SegmentedPreviewEngine(
            raw, fake, lambda t: None, interval=0.4, min_audio=0.5,
            segment_s=2.0, vad_silence_s=2.0,
            on_silence=lambda: fired.append(time.monotonic()))

    def drive_take(self, eng, raw, speech_s, silence_s, step=0.4):
        data = pcm(speech_s)
        raw.write_bytes(data)
        t = speech_s
        while t <= speech_s + silence_s + 1e-9:
            eng._tick(data, len(data) / BPS)
            t += step
            if t <= speech_s + silence_s:
                data += silence(step)
                raw.write_bytes(data)
        return data

    def test_fires_after_trailing_silence_with_speech(self, tmp_path):
        raw = tmp_path / "v.raw"
        raw.write_bytes(pcm(0.2))
        fired = []
        eng = self.make_engine(raw, lambda s: "hello world" if s > 1.5 else "",
                               fired)
        self.drive_take(eng, raw, speech_s=3.0, silence_s=2.6)
        assert len(fired) == 1
        assert any(eng.committed)  # only because real speech was committed

    def test_no_fire_on_all_silence_take(self, tmp_path):
        raw = tmp_path / "s.raw"
        raw.write_bytes(silence(0.2))
        fired = []
        eng = self.make_engine(raw, lambda s: "", fired)
        data = silence(8.0)
        raw.write_bytes(data)
        for t in (i * 0.5 + 0.5 for i in range(16)):
            eng._tick(data, t)
        assert fired == []
        assert eng.committed == ["", "", "", ""]  # decodes happened, all empty

    def test_short_silence_does_not_fire(self, tmp_path):
        raw = tmp_path / "sh.raw"
        raw.write_bytes(pcm(0.2))
        fired = []
        eng = self.make_engine(raw, lambda s: "hi" if s > 1.5 else "", fired)
        self.drive_take(eng, raw, speech_s=3.0, silence_s=1.2)
        assert fired == []

    def test_fires_at_most_once(self, tmp_path):
        raw = tmp_path / "once.raw"
        raw.write_bytes(pcm(0.2))
        fired = []
        eng = self.make_engine(raw, lambda s: "hi" if s > 1.5 else "", fired)
        data = self.drive_take(eng, raw, speech_s=3.0, silence_s=3.0)
        for _ in range(5):  # keep sitting in silence
            eng._tick(data, len(data) / BPS)
        assert len(fired) == 1

    def test_trailing_silence_unit(self):
        assert abs(trailing_silence_s(silence(1.0) + pcm(1.0)) - 0.0) < 0.02
        assert abs(trailing_silence_s(pcm(1.0) + silence(1.0)) - 1.0) < 0.02
        assert abs(trailing_silence_s(pcm(1.0) + silence(0.5)) - 0.5) < 0.02
        assert trailing_silence_s(b"") == 0.0
        # low-energy fricative tail is speech, not silence
        assert trailing_silence_s(pcm(1.0) + fricative(0.6)) < 0.02


class TestThreadedEngine:
    def test_end_to_end_growing_file(self, tmp_path):
        raw = tmp_path / "live.raw"
        raw.write_bytes(pcm(0.1))
        shown = []
        eng = SegmentedPreviewEngine(raw, lambda w, c: "word", shown.append,
                                     interval=0.08, min_audio=0.3,
                                     segment_s=2.0)
        eng.start()
        deadline = time.monotonic() + 6
        data = b""
        while len(shown) < 2 and time.monotonic() < deadline:
            data += pcm(0.3)
            raw.write_bytes(data)
            time.sleep(0.05)
        eng.stop(timeout=2)
        assert len(shown) >= 2
        assert eng.stats["decodes"] >= 2


class TestPreviewTranscriberFactory:
    def test_faster_whisper_gets_initial_prompt(self):
        kwargs = {}

        class Seg:
            text = "hi there"

        class Model:
            def transcribe(self, *a, **k):
                kwargs.update(k)
                return [Seg()], None

        backend = type("B", (), {"name": "faster-whisper", "_model": Model()})()
        made = preview_transcriber({}, backend, "en")
        assert made is not None
        fn, bname = made
        assert bname == "faster-whisper"
        from fluidvoice.audio_utils import raw_to_wav_bytes
        text = fn(raw_to_wav_bytes(pcm(0.2)), "context words")
        assert text == "hi there"
        assert kwargs["initial_prompt"] == "context words"
        assert kwargs["condition_on_previous_text"] is False

    def test_unready_backends_return_none(self):
        fw_loading = type("B", (), {"name": "faster-whisper", "_model": None})()
        assert preview_transcriber({}, fw_loading, "en") is None
        parakeet_cold = type("B", (), {"name": "parakeet", "_decoder": None})()
        assert preview_transcriber({}, parakeet_cold, "en") is None
        assert preview_transcriber({}, None, "en") is None

    def test_parakeet_ready_callable(self):
        import numpy as np

        class Feat:
            def __call__(self, samples):
                return np.zeros((10, 80), np.float32)

        class Dec:
            def run(self, feats):
                return [1, 2]

        backend = type("B", (), {
            "name": "parakeet", "_decoder": Dec(), "_featurizer": Feat(),
            "_normalize_type": "", "_id2tok": {1: "zdravo", 2: "svet"}})()
        fn, _ = preview_transcriber({}, backend, None)
        assert callable(fn)
        from fluidvoice.audio_utils import raw_to_wav_bytes
        # ctx is ignored (TDT has no prompt concept) but must not blow up;
        # detokenize joins TDT tokens without spaces (spacing rides the tokens)
        assert fn(raw_to_wav_bytes(pcm(0.2)), "ignored ctx") == "zdravosvet"

    def test_whisper_cpp_needs_binary_and_model(self):
        ready = type("B", (), {"name": "whisper.cpp", "binary": "/bin/true",
                               "model": "/tmp/m.bin"})()
        fn, bname = preview_transcriber({}, ready, "en")
        assert bname == "whisper.cpp" and callable(fn)
        not_ready = type("B", (), {"name": "whisper.cpp", "binary": None,
                                   "model": None})()
        assert preview_transcriber({}, not_ready, "en") is None
