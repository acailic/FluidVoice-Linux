"""Microphone recording via PipeWire (`pw-record`) or PulseAudio (`parecord`).

Produces 16 kHz mono s16 WAV files, matching FluidVoice's audio format.
"""
from __future__ import annotations

import shutil
import signal
import threading
import subprocess
import time
from pathlib import Path


class RecorderError(RuntimeError):
    pass


def pick_command(prefer: str = "auto") -> tuple[str, list[str]]:
    """Return (argv-prefix, wav-arg-style) for the first available recorder."""
    candidates: list[str]
    if prefer == "pw-record":
        candidates = ["pw-record"]
    elif prefer == "parecord":
        candidates = ["parecord"]
    else:
        candidates = ["pw-record", "parecord"]
    for cmd in candidates:
        if shutil.which(cmd):
            return cmd, []
    raise RecorderError("no recorder found: install pipewire (pw-record) or pulseaudio-utils (parecord)")


class Recorder:
    """Record 16 kHz mono s16 WAV to a file, started/stopped around a hotkey."""

    def __init__(self, command: str = "auto", device: str = "", sample_rate: int = 16000):
        self.command = command
        self.device = device
        self.sample_rate = sample_rate
        self.proc: subprocess.Popen | None = None
        self._path: Path | None = None
        self._started_at = 0.0

    @property
    def path(self) -> Path | None:
        return self._path

    def start(self, path: Path) -> None:
        if self.proc is not None:
            raise RecorderError("recorder already running")
        cmd, argv = pick_command(self.command)
        if cmd == "pw-record":
            args = [cmd, "--rate", str(self.sample_rate), "--channels", "1", "--format", "s16"]
            if self.device:
                args += ["--target", self.device]
        else:
            args = [cmd, f"--rate={self.sample_rate}", "--channels=1", "--format=s16le",
                    "--file-format=wav"]
            if self.device:
                args += ["--device", self.device]
        args += [str(path)]
        self._path = path
        self._started_at = time.monotonic()
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # Fail fast if the recorder dies immediately (bad device, no mic, ...)
        time.sleep(0.35)
        if self.proc.poll() is not None:
            stderr = (self.proc.stderr.read() or b"").decode(errors="replace").strip()
            self.proc = None
            raise RecorderError(f"{cmd} exited immediately: {stderr}")
        # Drain stderr for the rest of the session: a chatty recorder would
        # otherwise fill the 64 KB pipe buffer and silently block mid-recording.
        proc = self.proc

        def _drain(p: subprocess.Popen) -> None:
            try:
                p.stderr.read()
            except Exception:
                pass

        threading.Thread(target=_drain, args=(proc,), daemon=True).start()

    def stop(self, timeout: float = 5.0) -> Path | None:
        """Stop recording, finalize the WAV, return its path (None if nothing recorded)."""
        proc, path = self.proc, self._path
        self.proc, self._path = None, None
        if proc is None:
            return path
        # SIGINT lets pw-record/parecord flush + write the WAV header cleanly.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        return path

    def cancel(self) -> None:
        path = self.stop()
        if path and path.exists():
            path.unlink(missing_ok=True)

    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self.proc else 0.0
