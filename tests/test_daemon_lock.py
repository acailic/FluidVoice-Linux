"""Daemon singleton lock: XDG autostart + systemd both fire at login - the
second instance must exit immediately instead of fighting over the socket
and the hotkey grab (observed live as X BadAccess storms)."""
from __future__ import annotations

import pytest

from fluidvoice import cli


@pytest.fixture()
def isolated_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.paths, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(cli, "_DAEMON_LOCK_FILE", None)
    return tmp_path / "cfg" / "daemon.lock"


def test_second_instance_loses_lock(isolated_lock):
    first = cli._acquire_daemon_lock()
    assert first is not None
    try:
        assert cli._acquire_daemon_lock() is None
    finally:
        first.close()
    # released -> a fresh instance acquires again
    third = cli._acquire_daemon_lock()
    assert third is not None
    third.close()
    cli._DAEMON_LOCK_FILE.unlink(missing_ok=True)
