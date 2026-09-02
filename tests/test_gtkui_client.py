"""GTK-free client tests: daemon-down degraded mode (file-only saves).

Moved out of test_gtkui.py so headless boxes run them without a display:
fluidvoice.gtkui.client has no GTK imports by design.
"""
from __future__ import annotations

from fluidvoice.gtkui.client import Client


class TestClientFileOnlyMode:
    """Daemon-down degraded mode: file-only saves, file-based config reads."""

    @staticmethod
    def _dead_client() -> Client:
        from fluidvoice.gtkui.client import ClientError

        def boom(action, **kwargs):
            raise ClientError("daemon down")

        c = Client()
        c._request = boom
        return c

    def test_set_config_without_daemon_writes_file(self, tmp_path, monkeypatch):
        from fluidvoice import paths
        monkeypatch.setattr(paths, "config_file",
                            lambda: tmp_path / "c.toml")
        c = self._dead_client()
        resp = c.set_config({"sounds": {"volume": 0.4}})
        assert resp["ok"] and resp["changed"] == ["sounds.volume"]
        assert "file" in resp["note"]
        from fluidvoice.config import load_config
        assert load_config(tmp_path / "c.toml")["sounds"]["volume"] == 0.4

    def test_get_config_without_daemon(self):
        c = self._dead_client()
        cfg, from_daemon = c.get_config()
        assert from_daemon is False and cfg["hotkey"]["key"]
