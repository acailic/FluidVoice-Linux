"""Integration tests exercise real subsystems: PipeWire recording, CUDA
whisper, a real daemon subprocess with its socket + web UI, packaging, and
the installer download. Run with:  pytest -m integration
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

TEST_CONFIG = """\
[general]
language = "en"

[hotkey]
key = "F9"

[recording]
preview_enabled = false
skip_silent = false
first_pcm_timeout = 0

[sounds]
enabled = false

[notifications]
enabled = false

[history]
save = true

[server]
enabled = true
port = 0
"""


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    """Fully isolated config/data/socket environment (also for subprocesses)."""
    (tmp_path / "run").mkdir()
    (tmp_path / "data").mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(TEST_CONFIG)
    monkeypatch.setenv("FLUIDVOICE_CONFIG", str(cfg))
    # keep the real XDG_RUNTIME_DIR (PipeWire lives there); isolate the
    # control socket through its own override instead
    monkeypatch.setenv("FLUIDVOICE_SOCKET", str(tmp_path / "run" / "fluidvoice.sock"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return cfg


def _spawn_and_wait(tmp_path: Path, extra_args: list) -> subprocess.Popen:
    from fluidvoice import paths
    args = [str(REPO / ".venv/bin/fluidvoice"), "daemon", *extra_args]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            env={**os.environ})
    socket = paths.socket_path()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if socket.exists():
            break
        if proc.poll() is not None:
            (tmp_path / "daemon.log").write_text(proc.stdout.read())
            raise RuntimeError("daemon died at startup, log in %s" % (tmp_path / "daemon.log"))
        time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("daemon socket never appeared")
    return proc


def _stop_daemon(proc: subprocess.Popen, tmp_path: Path) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    if proc.stdout:
        (tmp_path / "daemon.log").write_text(proc.stdout.read())


@pytest.fixture()
def daemon_process(isolated_env, tmp_path):
    """A real daemon subprocess: socket control + web UI, no hotkey."""
    proc = _spawn_and_wait(tmp_path, ["--no-hotkey", "--no-sounds"])
    yield proc
    _stop_daemon(proc, tmp_path)


@pytest.fixture()
def daemon_with_hotkey(isolated_env, tmp_path):
    """A real daemon with its hotkey grab active (TEST_CONFIG: F9)."""
    proc = _spawn_and_wait(tmp_path, ["--no-sounds"])
    yield proc
    _stop_daemon(proc, tmp_path)


@pytest.fixture(scope="session")
def jfk_wav(tmp_path_factory) -> Path:
    """JFK sample as a 16 kHz mono WAV (downloaded once per session)."""
    import urllib.request
    flac = tmp_path_factory.mktemp("audio") / "jfk.flac"
    with urllib.request.urlopen(
            "https://github.com/openai/whisper/raw/main/tests/jfk.flac",
            timeout=60) as resp:
        flac.write_bytes(resp.read())
    wav = flac.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(flac),
                    "-ar", "16000", "-ac", "1", str(wav)], check=True)
    return wav
