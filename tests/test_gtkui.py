"""Offscreen GTK smoke tests for the native settings/history app.

Skipped without GTK4/libadwaita or a display, so the default suite stays
green on headless boxes. Windows are driven with a stub client: no daemon,
no real config/history files.
"""
from __future__ import annotations

import copy
import os
import time

import pytest

gi = pytest.importorskip("gi", reason="PyGObject not installed")
try:
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except ValueError as e:  # pragma: no cover - depends on the machine
    pytest.skip(f"GTK4/Adw unavailable: {e}", allow_module_level=True)
if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    pytest.skip("no display for GTK tests", allow_module_level=True)  # pragma: no cover

from gi.repository import Adw, GLib, Gtk  # noqa: E402

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
        cfg["processing"]["dictionary"] = [
            {"triggers": ["miro board"], "replacement": "Miro board"}]
        cfg["processing"]["filler_words"] = ["um", "uh", "eh"]
        cfg["general"]["language"] = "sl"
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

    def today_stats(self):
        return {"dictations": 2, "seconds": 6.5, "words": 9}

    def export_zip(self, path):
        self.exported_to = path
        return len(self.entries), ["skipped missing audio: x.wav"]

    def test_dictation(self, seconds=3.0):
        return {"ok": True, "text": "hello world", "duration_s": 3.0}


@pytest.fixture()
def loop():
    return GLib.MainLoop()


def pump(loop, ms=150):
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def pump_until(loop, cond, timeout_s=2.0):
    """Pump in short slices until cond() is truthy. A single fixed pump
    window is flaky under load: its quit timeout (priority 0) can starve
    GLib.idle_add sources (priority 200), so the idle callback may not
    have run by the time the loop quits."""
    deadline = time.monotonic() + timeout_s
    while not cond() and time.monotonic() < deadline:
        pump(loop, ms=20)
    return cond()


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

    def test_today_line_renders(self, loop):
        from fluidvoice.gtkui.main_window import HistoryWindow
        w = HistoryWindow(client=StubClient(ENTRIES))
        w.present()
        pump(loop)
        assert w.today_lbl.get_text() == "today: 2 dictations, 0:06 minutes, 9 words"
        w._load_history()  # refresh path updates it too
        assert w.today_lbl.get_text() == "today: 2 dictations, 0:06 minutes, 9 words"
        w.close()

    def test_today_line_survives_client_error(self, loop):
        from fluidvoice.gtkui.main_window import HistoryWindow
        c = StubClient(ENTRIES)

        def boom():
            raise RuntimeError("unreadable")

        c.today_stats = boom
        w = HistoryWindow(client=c)
        w.present()
        pump(loop)
        assert w.today_lbl.get_text() == ""  # unset, not a crash
        w.close()

    def test_export_action_registered(self, loop, monkeypatch):
        from fluidvoice.gtkui import main_window as mw
        installed = {}

        def spy(self, name, param, handler):
            installed[name] = handler  # record; no need to install here

        monkeypatch.setattr(mw.HistoryWindow, "install_action", spy)
        w = mw.HistoryWindow(client=StubClient(ENTRIES))
        w.present()
        pump(loop)
        # GTK 4.14 offers no lookup for widget-installed actions, so the
        # registration is verified through the install call itself
        assert callable(installed.get("hist.export"))
        assert installed["hist.export"] == w._on_export
        assert w._exporting is False
        # user-visible wiring: the menu offers Export… -> win.hist.export
        assert w.menu_model.get_n_items() == 2
        s = GLib.VariantType.new("s")
        label = w.menu_model.get_item_attribute_value(0, "label", s).get_string()
        action = w.menu_model.get_item_attribute_value(0, "action", s).get_string()
        assert label == "Export…" and action == "win.hist.export"
        w.close()

    def test_export_smoke(self, loop, tmp_path):
        from fluidvoice.gtkui.main_window import HistoryWindow
        c = StubClient(ENTRIES)
        w = HistoryWindow(client=c)
        w.present()
        pump(loop)
        enabled: list[tuple[str, bool]] = []
        w.action_set_enabled = lambda name, on: enabled.append((name, on))
        target = tmp_path / "h.zip"
        w._export_to(str(target))
        assert w._exporting is True  # busy until the idle callback runs
        assert enabled == [("hist.export", False)]
        assert pump_until(loop, lambda: not w._exporting)  # run the idle callback
        assert c.exported_to == str(target)
        assert w._exporting is False
        assert enabled == [("hist.export", False), ("hist.export", True)]
        w.close()

    def test_export_failure_toasts_and_reenables(self, loop, tmp_path):
        from fluidvoice.gtkui.main_window import HistoryWindow
        c = StubClient(ENTRIES)

        def broken(path):
            raise OSError("no space")

        c.export_zip = broken
        w = HistoryWindow(client=c)
        w.present()
        pump(loop)
        enabled: list[tuple[str, bool]] = []
        w.action_set_enabled = lambda name, on: enabled.append((name, on))
        w._export_to(str(tmp_path / "h.zip"))
        assert pump_until(loop, lambda: not w._exporting)
        assert w._exporting is False  # released even on failure
        assert enabled[-1] == ("hist.export", True)
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
        # command mode rows: hotkey capture + the [command] group (AI page)
        titles = {r.get_title() for r in w._rows.values()
                  if hasattr(r, "get_title")}
        assert any("Command key" in t for t in titles)
        assert any("Max agent turns" in t for t in titles)
        assert any("Working directory" in t for t in titles)
        assert ("command", "max_turns") in w._rows
        assert ("command", "confirm_timeout_s") in w._rows
        # About page reflects the daemon status poll (spec: backend, CUDA)
        assert w.about_backend_row.get_title() == "Backend"
        assert w.about_backend_row.get_subtitle() == "faster-whisper"
        assert w.about_gpu_row.get_title() == "GPU (CUDA)"
        assert w.about_gpu_row.get_subtitle() == "yes"
        w.close()

    def test_collect_roundtrip_and_save(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        body = w._collect()
        assert body["general"]["language"] == "sl"  # from the stub cfg
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

    def test_dictionary_and_filler_editing(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        # loaded from cfg
        assert len(w._dict_rows) == 1
        body = w._collect()
        assert body["processing"]["dictionary"] == [
            {"triggers": ["miro board"], "replacement": "Miro board"}]
        assert body["processing"]["filler_words"] == ["um", "uh", "eh"]
        assert body["general"]["language"] == "sl"
        # edit: add a word, change the filler list
        w._add_dict_word({"triggers": ["k8s"], "replacement": "Kubernetes"})
        w._dict_rows[0]["trig"].set_text("miro board, miro")
        w._dict_rows[0]["repl"].set_text("Miro board")
        w._rows[("processing", "filler_words")].row.set_text("um, ehm")
        body = w._collect()
        assert {"triggers": ["miro board", "miro"],
                "replacement": "Miro board"} in body["processing"]["dictionary"]
        assert {"triggers": ["k8s"], "replacement": "Kubernetes"} in \
            body["processing"]["dictionary"]
        assert body["processing"]["filler_words"] == ["um", "ehm"]
        # removal prunes the edited (first) entry, keeps the rest
        w._remove_dict_word(None, w._dict_rows[0])
        remaining = w._collect()["processing"]["dictionary"]
        assert {"triggers": ["miro board", "miro"],
                "replacement": "Miro board"} not in remaining
        assert remaining == [{"triggers": ["k8s"],
                              "replacement": "Kubernetes"}]
        w.close()

    def test_unknown_language_stays_selectable(self, loop):
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()
        c.get_config = lambda: (dict(copy.deepcopy(DEFAULTS), general={
            **copy.deepcopy(DEFAULTS)["general"], "language": "zz"}), True)
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        values = w._combo_values[("general", "language")]
        assert "zz" in values and "auto" in values
        assert w._collect()["general"]["language"] == "zz"
        w.close()

    def test_key_capture_maps_to_config_names(self):
        from fluidvoice.gtkui.settings_window import _keyname
        from gi.repository import Gdk
        assert _keyname(Gdk.keyval_from_name("Control_R")) == "Right_Control"
        assert _keyname(Gdk.keyval_from_name("F9")) == "F9"
        assert _keyname(Gdk.keyval_from_name("space")) == "space"
        assert _keyname(Gdk.keyval_from_name("q")) == "q"

    # -- whisper.cpp GGUF group --------------------------------------------------

    def test_gguf_group_rows_built(self, loop):
        from fluidvoice import model_catalog
        from fluidvoice.gtkui.settings_window import SettingsWindow
        w = SettingsWindow(client=StubClient())
        w.present()
        pump(loop)
        assert len(model_catalog.GGUF_CATALOG) == 7
        assert len(w._gguf_rows) == 7
        assert {r.get_title() for r in w._gguf_rows} == set(model_catalog.GGUF_CATALOG)
        w.close()

    def test_active_gguf_marker(self, loop):
        from fluidvoice import model_catalog
        from fluidvoice.gtkui.settings_window import SettingsWindow
        c = StubClient()

        def gg_cfg():
            cfg = copy.deepcopy(DEFAULTS)
            cfg["model"] = {**cfg["model"], "backend": "whisper.cpp",
                            "whispercpp_model": "ggml-small.bin"}
            return cfg, True

        c.get_config = gg_cfg
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        assert w._active_gguf() == "ggml-small.bin"

        def walk(widget):  # find suffix widgets under a row
            yield widget
            child = widget.get_first_child()
            while child:
                yield from walk(child)
                child = child.get_next_sibling()

        active_row = next(r for r in w._gguf_rows
                          if r.get_title() == "ggml-small.bin")
        labels = [x.get_text() for x in walk(active_row)
                  if isinstance(x, Gtk.Label)]
        assert "Active" in labels
        w.close()

    def test_download_flow_uses_worker_and_polls(self, loop, monkeypatch):
        from fluidvoice import model_catalog
        from fluidvoice.gtkui import settings_window as sw
        from fluidvoice.gtkui.settings_window import SettingsWindow
        downloaded = {"now": False}
        monkeypatch.setattr(sw.model_catalog, "gguf_downloaded",
                            lambda n: downloaded["now"])
        calls: list[tuple[str, list]] = []

        def fake_download(name, progress=None):
            seen: list = []
            calls.append((name, seen))
            if progress:
                seen.append(progress(50, 100))
                seen.append(progress(100, 100))
            return model_catalog.gguf_path(name)

        monkeypatch.setattr(sw.model_download, "download_gguf", fake_download)
        w = SettingsWindow(client=StubClient())
        w.present()
        pump(loop)
        w._download_gguf(None, "ggml-small.bin")
        assert pump_until(loop, lambda: w._gguf_dl["ggml-small.bin"].get("done"))
        st = w._gguf_dl["ggml-small.bin"]
        assert calls and calls[0][0] == "ggml-small.bin"
        assert st["total"] == 100 and st["error"] is None
        downloaded["now"] = True
        w._refresh_models()

        def walk(widget):
            yield widget
            child = widget.get_first_child()
            while child:
                yield from walk(child)
                child = child.get_next_sibling()

        row = next(r for r in w._gguf_rows if r.get_title() == "ggml-small.bin")
        buttons = [x.get_label() for x in walk(row) if isinstance(x, Gtk.Button)]
        assert buttons == ["Use"]
        w.close()

    def test_download_failure_toasts(self, loop, monkeypatch):
        from fluidvoice.gtkui import settings_window as sw
        from fluidvoice.gtkui.settings_window import SettingsWindow
        monkeypatch.setattr(sw.model_catalog, "gguf_downloaded", lambda n: False)

        def broken(name, progress=None):
            raise OSError("net down")

        monkeypatch.setattr(sw.model_download, "download_gguf", broken)
        w = SettingsWindow(client=StubClient())
        w.present()
        pump(loop)
        toasts: list[str] = []
        monkeypatch.setattr(w, "toast", lambda text, timeout=5: toasts.append(text))
        w._download_gguf(None, "ggml-base.bin")
        assert pump_until(loop, lambda: w._gguf_dl["ggml-base.bin"].get("error"))
        assert w._gguf_dl["ggml-base.bin"]["error"] == "net down"
        assert pump_until(loop, lambda: any("net down" in t for t in toasts))
        w.close()

    def test_use_gguf_posts_config(self, loop, monkeypatch):
        from fluidvoice.gtkui import settings_window as sw
        from fluidvoice.gtkui.settings_window import SettingsWindow
        monkeypatch.setattr(sw.model_catalog, "gguf_downloaded", lambda n: True)
        c = StubClient()
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        w._use_gguf(None, "ggml-base.bin")
        assert c.saved[-1]["model"] == {
            "backend": "whisper.cpp", "whispercpp_model": "ggml-base.bin"}
        pump(loop, 1300)  # let the scheduled warmup poll run once and stop
        w.close()

    def test_use_gguf_rejected_toasts(self, loop, monkeypatch):
        from fluidvoice.gtkui import settings_window as sw
        from fluidvoice.gtkui.settings_window import SettingsWindow
        monkeypatch.setattr(sw.model_catalog, "gguf_downloaded", lambda n: True)
        c = StubClient()

        def reject(body):
            return {"ok": False, "changed": [], "rejected": ["model.backend"],
                    "restart_required": [], "errors": [], "note": ""}

        c.set_config = reject
        w = SettingsWindow(client=c)
        w.present()
        pump(loop)
        toasts: list[str] = []
        monkeypatch.setattr(w, "toast", lambda text, timeout=5: toasts.append(text))
        w._use_gguf(None, "ggml-base.bin")
        assert any("model.backend" in t for t in toasts)
        assert c.saved == []
        w.close()


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
