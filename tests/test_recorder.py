from __future__ import annotations

import signal
import subprocess

import pytest

from fluidvoice import recorder as rec


class FakeProc:
    def __init__(self, *, exit_early=False, hang_on_int=False):
        self.exit_early = exit_early
        self.hang_on_int = hang_on_int
        self.signals: list = []
        self.stderr = subprocess.PIPE

    def poll(self):
        return 1 if self.exit_early else None

    def send_signal(self, sig):
        self.signals.append(sig)

    def terminate(self):
        self.send_signal(signal.SIGTERM)

    def kill(self):
        self.send_signal(signal.SIGKILL)

    def wait(self, timeout=None):
        if self.hang_on_int and signal.SIGINT in self.signals:
            raise subprocess.TimeoutExpired(cmd="pw-record", timeout=timeout)
        if self.exit_early:
            return 1
        return 0


@pytest.fixture()
def no_real_popen(monkeypatch):
    created: list[FakeProc] = []

    def fake_popen(args, **kwargs):
        proc = FakeProc(**kwargs.pop("_fake", {}))
        proc.stderr_read = b"device died"
        created.append(proc)
        return proc

    monkeypatch.setattr(rec.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rec.time, "sleep", lambda s: None)
    return created


class TestPickCommand:
    def test_prefers_pw_record(self, monkeypatch):
        monkeypatch.setattr(rec.shutil, "which",
                            lambda n: "/usr/bin/" + n if n == "pw-record" else None)
        cmd, _ = rec.pick_command("auto")
        assert cmd == "pw-record"

    def test_falls_back_to_parecord(self, monkeypatch):
        monkeypatch.setattr(rec.shutil, "which",
                            lambda n: "/usr/bin/" + n if n == "parecord" else None)
        cmd, _ = rec.pick_command("auto")
        assert cmd == "parecord"

    def test_explicit_preference_missing_raises(self, monkeypatch):
        monkeypatch.setattr(rec.shutil, "which",
                            lambda n: "/usr/bin/" + n if n == "parecord" else None)
        with pytest.raises(rec.RecorderError):
            rec.pick_command("pw-record")  # explicit choice, not installed -> error

    def test_none_available(self, monkeypatch):
        monkeypatch.setattr(rec.shutil, "which", lambda n: None)
        with pytest.raises(rec.RecorderError):
            rec.pick_command("auto")


class TestRecorderLifecycle:
    def test_start_immediate_exit_raises(self, monkeypatch, tmp_path):
        import io

        class DeadProc:
            def poll(self):
                return 1

            stderr = io.BytesIO(b"failed to link")

        monkeypatch.setattr(rec.subprocess, "Popen", lambda args, **kw: DeadProc())
        monkeypatch.setattr(rec.time, "sleep", lambda s: None)
        r = rec.Recorder()
        with pytest.raises(rec.RecorderError, match="failed to link"):
            r.start(tmp_path / "x.wav")
        assert r.proc is None

    def test_stop_sends_sigint_and_returns_path(self, no_real_popen, tmp_path):
        r = rec.Recorder()
        r.start(tmp_path / "x.wav")
        path = r.stop()
        assert path == tmp_path / "x.wav"
        assert no_real_popen[0].signals == [signal.SIGINT]
        assert r.proc is None

    def test_stop_escalates_on_hang(self, monkeypatch, tmp_path):
        instances: list = []

        class Stubborn(FakeProc):
            def wait(self, timeout=None):
                # ignores SIGINT, yields once SIGTERM/SIGKILL arrives
                if signal.SIGTERM in self.signals or signal.SIGKILL in self.signals:
                    return 0
                raise subprocess.TimeoutExpired(cmd="pw", timeout=timeout)

        def popen(args, **kw):
            proc = Stubborn()
            instances.append(proc)
            return proc

        monkeypatch.setattr(rec.subprocess, "Popen", popen)
        monkeypatch.setattr(rec.time, "sleep", lambda s: None)
        r = rec.Recorder()
        r.start(tmp_path / "x.wav")
        path = r.stop(timeout=0.1)
        assert path == tmp_path / "x.wav"
        # escalation order: SIGINT first, then SIGTERM
        assert instances[0].signals[:2] == [signal.SIGINT, signal.SIGTERM]

    def test_stop_without_start(self, tmp_path):
        r = rec.Recorder()
        assert r.stop() is None

    def test_cancel_discards_file(self, tmp_path):
        r = rec.Recorder()
        wav = tmp_path / "x.wav"
        wav.write_bytes(b"\0" * 500)

        class Simple:
            def send_signal(self, s):
                pass

            def wait(self, timeout=None):
                return 0

        r.proc = Simple()
        r._path = wav
        r.cancel()
        assert not wav.exists()
