import json
import threading
from pathlib import Path

from fluidvoice import control
from fluidvoice.config import DEFAULTS, load_config


class TestConfig:
    def test_defaults_complete(self):
        for section in ("general", "hotkey", "recording", "model", "processing",
                        "ai", "insertion", "sounds", "notifications", "history"):
            assert section in DEFAULTS

    def test_load_missing_file_gives_defaults(self, tmp_path: Path):
        cfg = load_config(tmp_path / "missing.toml")
        assert cfg["hotkey"]["key"] == "Right_Control"
        assert cfg["ai"]["enabled"] is False

    def test_load_overrides(self, tmp_path: Path):
        f = tmp_path / "c.toml"
        f.write_text('[hotkey]\nkey = "F9"\n[ai]\nenabled = true\n')
        cfg = load_config(f)
        assert cfg["hotkey"]["key"] == "F9"
        assert cfg["hotkey"]["mode"] == "toggle"  # untouched default
        assert cfg["ai"]["enabled"] is True


class TestControlSocket:
    def test_round_trip(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(control.paths, "socket_path", lambda: tmp_path / "s.sock")
        state = {"recording": False}

        def handler(req):
            if req["action"] == "toggle":
                state["recording"] = not state["recording"]
            return {"ok": True, "recording": state["recording"]}

        srv = control.serve(handler)
        try:
            r1 = control.request("toggle")
            r2 = control.request("toggle")
            assert r1 == {"ok": True, "recording": True}
            assert r2 == {"ok": True, "recording": False}
        finally:
            srv.close()

    def test_no_daemon(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(control.paths, "socket_path", lambda: tmp_path / "nope.sock")
        try:
            control.request("toggle")
            assert False, "expected ControlError"
        except control.ControlError:
            pass
