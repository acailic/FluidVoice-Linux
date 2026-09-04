"""Lock suppression: lockmon's transition-only state machine + the daemon's
locked gate (hotkeys ignored, active dictation cancelled, tooltip notes
`paused (locked)`). The bus wiring itself is a live concern (documented
manual check in docs/STATUS.md); here every handler is driven directly,
exactly the way D-Bus would call it."""
from __future__ import annotations

import copy
import math
import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from fluidvoice import daemon as dm
from fluidvoice.config import DEFAULTS
from fluidvoice.lockmon import (MANAGER_PATH, LockMonitor,
                                session_path_from_env)


# ---------------------------------------------------------------------------
# LockMonitor: transitions only
# ---------------------------------------------------------------------------

def _monitor(logs=None):
    flips: list[bool] = []
    logs = logs if logs is not None else []
    mon = LockMonitor(on_change=flips.append, log=logs.append)
    return mon, flips, logs


class TestApplyDedup:
    def test_same_value_no_callback(self):
        mon, flips, _ = _monitor()
        mon._apply(True, "Lock")
        mon._apply(True, "LockedHint")  # GNOME's duplicate source
        mon._apply(True, "reconcile")
        assert flips == [True]
        assert mon.locked is True

    def test_flip_sequence(self):
        mon, flips, _ = _monitor()
        mon._apply(True, "Lock")
        mon._apply(False, "Unlock")
        mon._apply(False, "reconcile")
        mon._apply(True, "PrepareForSleep")
        assert flips == [True, False, True]

    def test_initial_unlocked_stays_silent(self):
        # an unlocked start is the assumed baseline: no callback
        mon, flips, _ = _monitor()
        mon._apply(False, "reconcile")
        assert flips == []
        mon._apply(True, "reconcile")
        assert flips == [True]

    def test_callback_failure_is_contained(self):
        mon = LockMonitor(on_change=lambda l: (_ for _ in ()).throw(
            RuntimeError("boom")), log=(lambda m: None))
        assert mon._apply(True, "Lock") is True  # state applied anyway
        assert mon.locked is True


class TestSignalHandlers:
    def test_logind_lock_unlock(self):
        mon, flips, _ = _monitor()
        mon._on_session_lock()
        mon._on_session_unlock()
        assert flips == [True, False]

    def test_properties_changed_locked_hint(self):
        mon, flips, _ = _monitor()
        mon._on_session_props_changed("org.freedesktop.login1.Session",
                                      {"LockedHint": True}, [])
        assert flips == [True]
        mon._on_session_props_changed("org.freedesktop.login1.Session",
                                      {"IdleHint": True}, [])  # not ours
        assert flips == [True]

    def test_prepare_for_sleep(self):
        mon, flips, _ = _monitor()
        mon._on_prepare_for_sleep(True)
        mon._on_prepare_for_sleep(False)
        assert flips == [True, False]

    def test_screensaver_active_changed(self):
        mon, flips, _ = _monitor()
        mon._on_screensaver_active(True)
        mon._on_screensaver_active(False)
        assert flips == [True, False]

    def test_one_flip_across_sources(self):
        # Lock signal THEN PropertiesChanged with the same value: one flip
        mon, flips, _ = _monitor()
        mon._on_session_lock()
        mon._on_session_props_changed("s", {"LockedHint": True}, [])
        mon._on_screensaver_active(True)
        assert flips == [True]


class TestSessionPath:
    def test_env_id_builds_path(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_ID", "4")
        assert session_path_from_env() == f"{MANAGER_PATH}/session/4"

    def test_env_id_missing_or_weird(self, monkeypatch):
        monkeypatch.delenv("XDG_SESSION_ID", raising=False)
        assert session_path_from_env() is None
        monkeypatch.setenv("XDG_SESSION_ID", "  ")
        assert session_path_from_env() is None
        monkeypatch.setenv("XDG_SESSION_ID", "../evil")
        assert session_path_from_env() is None

    def test_env_wins_over_pid_lookup(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_ID", "7")

        class _Mgr:
            def GetSessionByPID(self, *_a, **_k):
                raise AssertionError("must not be called")

        mon, _, _ = _monitor()
        assert mon._session_path(manager=_Mgr()) == \
            f"{MANAGER_PATH}/session/7"

    def test_pid_fallback(self, monkeypatch):
        monkeypatch.delenv("XDG_SESSION_ID", raising=False)

        class _Mgr:
            def GetSessionByPID(self, pid, timeout=5):
                assert timeout
                return f"{MANAGER_PATH}/session/c1"

        mon, _, _ = _monitor()
        assert mon._session_path(manager=_Mgr()) == \
            f"{MANAGER_PATH}/session/c1"

    def test_pid_fallback_error_returns_none(self, monkeypatch):
        monkeypatch.delenv("XDG_SESSION_ID", raising=False)

        class _Mgr:
            def GetSessionByPID(self, *_a, **_k):
                raise RuntimeError("NoSessionForPID")

        mon, _, logs = _monitor()
        assert mon._session_path(manager=_Mgr()) is None
        assert any("session lookup failed" in m for m in logs)

    def test_no_bus_no_manager(self, monkeypatch):
        monkeypatch.delenv("XDG_SESSION_ID", raising=False)
        mon, _, _ = _monitor()
        assert mon._session_path() is None


# ---------------------------------------------------------------------------
# Daemon lock gate
# ---------------------------------------------------------------------------

def _make_wav(path: Path) -> Path:
    n = 16000
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / 16000)))
            for i in range(n)))
    return path


class _StubRecorder:
    """Records start/stop/cancel - asserts the cancel path was used."""

    def __init__(self):
        self.started = 0
        self.stopped = 0
        self.cancelled = 0

    def start(self, path):
        _make_wav(path)
        self.started += 1

    def stop(self):
        self.stopped += 1
        return None  # no audio: the daemon logs "no audio captured"

    def cancel(self):
        self.cancelled += 1


@pytest.fixture()
def lockd(tmp_path, monkeypatch):
    """Daemon with stub recorder, quiet UI, injected log capture."""
    calls = {"notify": [], "sound": []}

    def fake_notify(title, body="", timeout_ms=2500, enabled=True):
        if enabled:
            calls["notify"].append((title, body))

    def fake_sound(which, volume=1.0, enabled=True):
        calls["sound"].append(which)

    logs: list[str] = []
    monkeypatch.setattr(dm, "log", logs.append)
    monkeypatch.setattr(dm.ui, "notify", fake_notify)
    monkeypatch.setattr(dm.ui, "play_sound", fake_sound)
    monkeypatch.setattr(dm.insertion, "active_window_class", lambda: "TestApp")
    monkeypatch.setattr(dm.history_mod.paths, "history_file",
                        lambda: tmp_path / "history.jsonl")

    def _make(pause_when_locked=True):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["general"]["pause_when_locked"] = pause_when_locked
        rec = _StubRecorder()
        d = dm.Daemon(cfg, recorder=rec, use_hotkey=False, use_sounds=False)
        return SimpleNamespace(d=d, rec=rec, logs=logs, calls=calls)

    return _make


class TestDaemonLockedGate:
    def test_toggle_ignored_while_locked(self, lockd):
        h = lockd()
        h.d._locked = True
        assert h.d.toggle() is False
        assert h.rec.started == 0
        assert h.d.recording is False
        assert "paused (locked)" in h.d._tray_tooltip()

    def test_lock_cancels_active_recording(self, lockd):
        h = lockd()
        assert h.d.toggle() is True
        h.d._locked = True
        h.d._on_locked(True)
        assert h.rec.cancelled == 1
        assert h.d.recording is False
        assert any(body == "Cancelled" for _t, body in h.calls["notify"])

    def test_unlock_resumes_normal_toggles(self, lockd):
        h = lockd()
        h.d._locked = True
        assert h.d.toggle() is False
        h.d._on_locked(False)
        h.d._locked = False
        assert h.d.toggle() is True
        assert h.rec.started == 1

    def test_lock_logs_each_transition_once(self, lockd):
        h = lockd()
        h.d._locked = True
        h.d._on_locked(True)
        h.d.toggle()  # ignored quietly
        h.d.toggle()  # ignored quietly
        assert h.logs.count("screen locked - hotkeys paused") == 1
        assert h.logs.count("screen unlocked - hotkeys resumed") == 0
        h.d._on_locked(False)
        h.d._locked = False
        assert h.logs.count("screen unlocked - hotkeys resumed") == 1

    def test_rewrite_and_command_gated_while_locked(self, lockd):
        h = lockd()
        h.d._locked = True
        h.d.start_rewrite()
        h.d.start_command()
        assert h.rec.started == 0

    def test_lock_cancels_pending_command(self, lockd):
        h = lockd()
        h.d._command_pending = True
        h.d._command_session = SimpleNamespace(cancel=lambda: None)
        h.d._locked = True
        h.d._on_locked(True)
        assert h.d._command_pending is False

    def test_socket_cancel_still_works_while_locked(self, lockd):
        h = lockd()
        assert h.d.toggle() is True
        h.d._locked = True
        resp = h.d.handle_request({"action": "cancel"})
        assert resp["ok"] is True and resp["recording"] is False
        assert h.rec.cancelled == 1

    def test_status_reports_locked(self, lockd):
        h = lockd()
        assert h.d.handle_request({"action": "status"})["locked"] is False
        h.d._locked = True
        assert h.d.handle_request({"action": "status"})["locked"] is True

    def test_pause_when_locked_false_never_gates(self, lockd):
        h = lockd(pause_when_locked=False)
        h.d._start_lockmon()
        assert h.d._lockmon is None  # monitor never started
        h.d._locked = True  # even a stale state cannot gate
        h.d._locked = False
        assert h.d.toggle() is True

    def test_disabled_setting_logs_nothing(self, lockd):
        h = lockd(pause_when_locked=False)
        h.d._start_lockmon()
        assert not any("lock" in m for m in h.logs)


class TestDaemonLockmonWiring:
    def test_start_lockmon_success(self, lockd, monkeypatch):
        h = lockd()
        started = []

        class _StubMon:
            def __init__(self, on_change, log=None):
                self.on_change = on_change
                self.stopped = False

            def start(self):
                started.append(1)
                return True

            def stop(self):
                self.stopped = True

        import fluidvoice.lockmon as lockmon
        monkeypatch.setattr(lockmon, "LockMonitor", _StubMon)
        h.d._start_lockmon()
        assert started == [1]
        assert h.d._lockmon is not None
        # the callback routes into the daemon's lock gate
        h.d._lockmon.on_change(True)
        h.d._locked = True
        assert "screen locked - hotkeys paused" in h.logs
        mon = h.d._lockmon
        h.d.shutdown()
        assert mon.stopped is True

    def test_start_lockmon_failure_continues(self, lockd, monkeypatch):
        h = lockd()

        class _StubMon:
            def __init__(self, on_change, log=None):
                pass

            def start(self):
                return False

            def stop(self):
                pass

        import fluidvoice.lockmon as lockmon
        monkeypatch.setattr(lockmon, "LockMonitor", _StubMon)
        h.d._start_lockmon()  # logged inside, daemon continues
        assert h.d._lockmon is None

    def test_apply_config_flips_lock_pause_live(self, lockd, monkeypatch):
        h = lockd()
        stopped = []

        class _StubMon:
            def __init__(self, on_change, log=None):
                pass

            def start(self):
                return True

            def stop(self):
                stopped.append(1)

        import fluidvoice.lockmon as lockmon
        monkeypatch.setattr(lockmon, "LockMonitor", _StubMon)
        h.d._lockmon = _StubMon(None)
        h.d._locked = True
        h.d.cfg["general"]["pause_when_locked"] = False
        feedback = h.d.apply_config(["general.pause_when_locked"])
        assert "lock pause" in feedback["applied"]
        assert stopped == [1]
        assert h.d._lockmon is None
        assert h.d._locked is False  # paused state cleared
