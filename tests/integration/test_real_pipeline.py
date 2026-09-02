"""Real audio subsystems: pw-record capture, raw->WAV, GPU transcription,
streaming preview engine with the real model."""
import subprocess
import time
from pathlib import Path

import pytest

from fluidvoice import backends
from fluidvoice.audio_utils import duration_seconds, raw_to_wav_file
from fluidvoice.config import load_config
from fluidvoice.preview import PreviewEngine, faster_whisper_transcriber

pytestmark = [pytest.mark.integration, pytest.mark.slow]


class TestRealRecorder:
    def test_pw_record_roundtrip(self, tmp_path):
        from fluidvoice.recorder import Recorder
        rec = Recorder()
        wav = tmp_path / "live.wav"
        rec.start(wav)
        assert rec.raw_path is not None and rec.raw_path.exists()
        time.sleep(1.5)  # capture ~1.5s from the real microphone
        raw = rec.raw_path
        out = rec.stop()
        assert out == wav
        assert wav.exists()
        assert duration_seconds(str(wav)) >= 1.2
        assert not raw.exists() and rec.raw_path is None

    def test_cancel_cleans_up(self, tmp_path):
        from fluidvoice.recorder import Recorder
        rec = Recorder()
        rec.start(tmp_path / "c.wav")
        time.sleep(0.5)
        raw = rec.raw_path
        rec.cancel()
        assert not (tmp_path / "c.wav").exists()
        assert not raw.exists()


class TestRealTranscription:
    def test_gpu_transcription_of_jfk(self, jfk_wav, shared_backend):
        backend = shared_backend
        result = backend.transcribe(jfk_wav, language="en")
        text = result["text"].lower()
        assert "fellow americans" in text or "my fellow" in text

    def test_raw_pipeline_transcription(self, jfk_wav, tmp_path, shared_backend):
        # flac->wav->raw->wav mirrors exactly what the recorder produces
        raw = tmp_path / "j.raw"
        import wave
        with wave.open(str(jfk_wav)) as wf:
            data = wf.readframes(wf.getnframes())
        raw.write_bytes(data)
        wrapped = tmp_path / "j.wav"
        raw_to_wav_file(raw, wrapped, 16000)
        backend = shared_backend
        result = backend.transcribe(wrapped, language="en")
        assert "americans" in result["text"].lower()


class TestRealPreviewEngine:
    def test_streaming_partials_with_real_model(self, jfk_wav, tmp_path, shared_backend):
        import wave
        with wave.open(str(jfk_wav)) as wf:
            pcm = wf.readframes(wf.getnframes())
        backend = shared_backend
        assert backend._model is not None
        engine = PreviewEngine(
            tmp_path / "live.raw",
            faster_whisper_transcriber(backend._model, "en"),
            lambda t: None, interval=0.8, min_audio=1.0)
        engine.start()
        chunk = int(0.4 * 32000)
        for i in range(0, len(pcm), chunk):
            with open(engine.raw_path, "ab") as fh:
                fh.write(pcm[i:i + chunk])
            time.sleep(0.4)
        engine.stop(timeout=5)
        assert "americans" in engine.last_text.lower()
