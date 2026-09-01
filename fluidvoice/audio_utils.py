"""Small audio helpers (silence gate, mirroring FluidVoice's thresholds)."""
from __future__ import annotations

import wave
from dataclasses import dataclass


@dataclass
class AudioStats:
    peak: float
    rms: float
    max_frame_rms: float  # 20 ms frames


def wav_stats(path: str) -> AudioStats:
    with wave.open(str(path), "rb") as wf:
        n = wf.getnframes()
        rate = wf.getframerate() or 16000
        raw = wf.readframes(n)
    import array
    samples = array.array("h")
    samples.frombytes(raw[: (len(raw) // 2) * 2])
    if not samples:
        return AudioStats(0.0, 0.0, 0.0)
    floats = [s / 32768.0 for s in samples]
    peak = max(abs(v) for v in floats)
    rms = (sum(v * v for v in floats) / len(floats)) ** 0.5
    frame = max(1, int(rate * 0.02))
    max_frame = 0.0
    for i in range(0, len(floats), frame):
        chunk = floats[i : i + frame]
        if chunk:
            fr = (sum(v * v for v in chunk) / len(chunk)) ** 0.5
            max_frame = max(max_frame, fr)
    return AudioStats(peak=peak, rms=rms, max_frame_rms=max_frame)


def is_silent(path: str) -> bool:
    """FluidVoice's short-recording silence gate."""
    stats = wav_stats(path)
    return stats.peak < 0.01 and stats.rms < 0.002 and stats.max_frame_rms < 0.0045


def duration_seconds(path: str) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 16000)


def pad_wav(path, rate: int = 16000, frame_width: int = 2) -> None:
    """Zero-pad sub-1s audio to exactly `rate` samples (16000). Upstream does
    this unconditionally - whisper.cpp asserts on <1s inputs."""
    import wave as _wave
    with _wave.open(str(path), "rb") as wf:
        n = wf.getnframes()
        params = wf.getparams()
        data = wf.readframes(n)
    if n >= rate or params.nframes == 0:
        return
    with _wave.open(str(path), "wb") as wf_out:
        wf_out.setparams(params)
        wf_out.writeframes(data)
        wf_out.writeframes(b"\x00" * (rate - n) * params.nchannels * frame_width)
