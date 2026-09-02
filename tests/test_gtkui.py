"""Offscreen GTK smoke tests for the native settings/history app.

Skipped without GTK4/libadwaita or a display, so the default suite stays
green on headless boxes. Windows are driven with a stub client: no daemon,
no real config/history files.
"""
from __future__ import annotations

import copy
import os

import pytest

gi = pytest.importorskip("gi", reason="PyGObject not installed")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except ValueError as e:  # pragma: no cover - depends on the machine
    pytest.skip(f"GTK4/Adw unavailable: {e}", allow_module_level=True)
if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("no display for GTK tests", allow_module_level=True)  # pragma: no cover

from gi.repository import Adw, GLib  # noqa: E402

from fluidvoice.config import DEFAULTS  # noqa: E402
from fluidvoice.gtkui.client import Client  # noqa: E402

Adw.init()


class StubClient(Client):
    """Deterministic client: fixture config/history, records saves."""

    def __init__(self, entries=None):
        super().__init__()
        self.entries = entries or []
        self.saved: list[dict] = []
        self.selected_models: list[str] = []

    def status(self):
        return {"ok": True, "recording": False, "busy": False,
                "backend": "faster-whisper", "cuda": True,
                "warmup": {"running": False, "error": None, "model": None}}

    def daemon_alive(self):
        return True

    def get_config(self):
        cfg = copy.deepcopy(DEFAULTS)
        cfg["ai"]["per_app_prompts"] = [
            {"apps": ["zed"], "instructions": "keep it terse"}]
        return cfg, True

    def set_config(self, body):
        self.saved.append(body)
        changed = [f"{s}.{k}" for s, keys in body.items() for k in keys]
        return {"ok": True, "changed": changed, "rejected": [],
                "restart_required": [], "errors": [], "note": ""}

    def select_model(self, name):
        self.selected_models.append(name)
        return {"ok": True, "model": name}

    def history(self, q="", limit=200):
        q = (q or "").lower()
        return [e for e in self.entries
                if q in str(e.get("text", "")).lower()
                or q in str(e.get("app", "")).lower()]

    def history_delete(self, ts):
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.get("ts") != ts]
        return before - len(self.entries)

    def history_clear(self):
        n = len(self.entries)
        self.entries = []
        return n

    def test_dictation(self, seconds=3.0):
        return {"ok": True, "text": "hello world", "duration_s": 3.0}


@pytest.fixture()
def loop():
    return GLib.MainLoop()


def pump(loop, ms=150):
    GLib.timeout_add(ms, loop.quit)
    loop.run()


ENTRIES = [
    {"ts": 1756800000.0, "text": "first entry", "duration_s": 2.5,
     "app": "firefox", "ai": False},
    {"ts": 1756800600.0, "text": "polished entry", "duration_s": 4.0,
     "ai": True, "audio": True},
]


class TestHistoryWindow:
    def test_populates_and_search_filters(self, loop):
        from fluidvoice.gtkui.main_window import HistoryWindow
        c = StubClient(ENTRIES)
        w = HistoryWindow(client=c)
        w.present()
        pump(loop)
        assert w._entries and len(w._entries) == 2
        w._query = "polished"
        w._load_history()
        assert len(w._entries) == 1
        w._query = "firefox"
        w._load_history()
        assert len(w._entries) == 1 and w._entries[0]["app"] == "firefox"
        w.close()

    def test_status_reflects_daemon(self, loop):
        from fluidvoice.gtkui.main_window import HistoryWindow
        w = HistoryWindow(client=StubClient(ENTRIES))
        w.present()
        pump(loop)
        w._apply_status({"recording": True, "busy": False,
                         "backend": "b", "cuda": False})
        assert w.state_lbl.get_text() == "recording"
        w._apply_status(None)
        assert w.down_banner.get_revealed() is True
        w.close()


class TestSettingsWindow:
    def test_loads_every_section(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        w = SettingsWindow(client=StubClient())
        w.present()
        pump(loop)
        # every whitelisted settings family has a row registered
        fams = {sec for sec, _k in w._rows}
        assert {"general", "hotkey", "recording", "model", "processing",
                "ai", "insertion", "sounds", "notifications",
                "history"} <= fams
        assert len(w._rows) >= 40
        w.close()

    def test_collect_roundtrip_and_save(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        body = w._collect()
        assert body["general"]["language"] == DEFAULTS["general"]["language"]
        assert body["sounds"]["volume"] == 1.0
        assert body["hotkey"]["modifiers"] == []
        assert body["ai"]["per_app_prompts"] == [
            {"apps": ["zed"], "instructions": "keep it terse"}]
        # flip two controls -> dirty -> save posts them
        w._rows[("sounds", "enabled")].set_active(False)
        w._rows[("recording", "preview_enabled")].set_active(False)
        assert w._dirty is True
        w.save()
        assert c.saved and c.saved[-1]["sounds"]["enabled"] is False
        assert c.saved[-1]["recording"]["preview_enabled"] is False
        w.close()

    def test_per_app_rule_editing(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        assert len(w._rule_rows) == 1  # loaded from cfg
        w._add_rule({"apps": ["firefox"], "instructions": "bullets"})
        w._rule_rows[0]["apps"].set_text("zed, code")
        w._rule_rows[0]["buf"].set_text("be terse")
        rules = w._collect_rules()
        assert {"apps": ["zed", "code"], "instructions": "be terse"} in rules
        assert {"apps": ["firefox"], "instructions": "bullets"} in rules
        w.close()

    def test_key_capture_maps_to_config_names(self):
        from fluidvoice.gtkui.settings_window import _keyname
        from gi.repository import Gdk
        assert _keyname(Gdk.keyval_from_name("Control_R")) == "Right_Control"
        assert _keyname(Gdk.keyval_from_name("F9")) == "F9"
        assert _keyname(Gdk.keyval_from_name("space")) == "space"
        assert _keyname(Gdk.keyval_from_name("q")) == "q"


class TestOnboardingWindow:
    def test_populates_and_tryout(self, loop):
        from fluidvoice.gtkui.onboarding import OnboardingWindow
        w = OnboardingWindow(client=StubClient())
        w.present()
        pump(loop)
        assert "Right_Control" in w.hotkey_lbl.get_text() or \
            "Right_Control" in w.hotkey_lbl.get_label()
        w._show_tryout({"ok": True, "text": "hello", "duration_s": 3})
        assert "hello" in w.try_out.get_text()
        w.close()


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
