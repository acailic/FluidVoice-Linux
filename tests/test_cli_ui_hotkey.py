from __future__ import annotations

from pathlib import Path

import pytest

from fluidvoice import cli, paths, ui
from fluidvoice.hotkey import MODIFIER_MASKS, HotkeyError, resolve_keysym


class TestResolveKeysym:
    def test_friendly_aliases(self):
        assert resolve_keysym("Right_Control") == resolve_keysym("Control_R")
        assert resolve_keysym("right_ctrl") == resolve_keysym("Control_R")
        assert resolve_keysym("Right_Alt") == resolve_keysym("Alt_R")
        assert resolve_keysym("right_option") == resolve_keysym("Alt_R")
        assert resolve_keysym("Left_Control") == resolve_keysym("Control_L")
        assert resolve_keysym("esc") == resolve_keysym("Escape")

    def test_plain_names(self):
        assert resolve_keysym("F9") != 0
        assert resolve_keysym("space") != 0
        # multi-word normalization: "page up" -> "Page_Up"
        assert resolve_keysym("page up") == resolve_keysym("Page_Up")
        assert resolve_keysym("right control") == resolve_keysym("Control_R")

    def test_unknown_raises(self):
        with pytest.raises(HotkeyError, match="unknown key name"):
            resolve_keysym("make_me_a_sandwich")

    def test_modifier_masks_complete(self):
        assert set(MODIFIER_MASKS) == {"ctrl", "alt", "shift", "super"}
        assert all(v != 0 for v in MODIFIER_MASKS.values())


class TestUI:
    def test_notify_without_tool_is_silent(self, monkeypatch):
        ran = []
        monkeypatch.setattr(ui.shutil, "which", lambda n: None)
        monkeypatch.setattr(ui.subprocess, "run", lambda *a, **k: ran.append(a))
        ui.notify("t", "b", enabled=True)
        assert ran == []

    def test_notify_calls_notify_send(self, monkeypatch):
        ran = []
        monkeypatch.setattr(ui.shutil, "which", lambda n: "/usr/bin/" + n)
        monkeypatch.setattr(ui.subprocess, "run", lambda *a, **k: ran.append(a))
        ui.notify("Title", "Body", timeout_ms=1500, enabled=True)
        assert ran and ran[0][0][:3] == ["notify-send", "-a", "FluidVoice"]

    def test_notify_disabled(self, monkeypatch):
        ran = []
        monkeypatch.setattr(ui.shutil, "which", lambda n: "/usr/bin/" + n)
        monkeypatch.setattr(ui.subprocess, "run", lambda *a, **k: ran.append(a))
        ui.notify("t", enabled=False)
        assert ran == []

    def test_play_sound_unknown_name_noop(self, monkeypatch):
        monkeypatch.setattr(ui.shutil, "which", lambda n: "/usr/bin/" + n)
        ui.play_sound("explosion", enabled=True)  # must not raise

    def test_play_sound_disabled(self, monkeypatch):
        monkeypatch.setattr(ui.shutil, "which", lambda n: "/usr/bin/" + n)
        ui.play_sound("start", enabled=False)  # must not raise


class TestCliConfig:
    def test_config_init(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "config.toml"
        monkeypatch.setattr(paths, "config_file", lambda: target)
        assert cli.main(["config", "init"]) == 0
        assert "Right_Control" in target.read_text()
        out = capsys.readouterr().out
        assert str(target) in out

    def test_config_path(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "config.toml"
        monkeypatch.setattr(paths, "config_file", lambda: target)
        cli.main(["config", "path"])
        assert str(target) in capsys.readouterr().out

    def test_config_print(self, tmp_path, monkeypatch, capsys):
        target = tmp_path / "config.toml"
        monkeypatch.setattr(paths, "config_file", lambda: target)
        target.write_text('[hotkey]\nkey = "F9"\n')
        cli.main(["config", "print"])
        assert 'key = "F9"' in capsys.readouterr().out

    def test_config_print_missing(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(paths, "config_file",
                            lambda: tmp_path / "missing.toml")
        cli.main(["config", "print"])
        assert "no config file" in capsys.readouterr().out


class TestCliHistory:
    def test_history_output(self, monkeypatch, capsys):
        from fluidvoice import history
        entries = [{"ts": 1700000000, "text": "hello", "ai": True},
                   {"ts": 1700000001, "text": "world", "ai": False}]
        monkeypatch.setattr(history, "tail", lambda n=10: entries[:n])
        assert cli.main(["history", "-n", "2"]) == 0
        out = capsys.readouterr().out
        assert "[AI]: hello" in out
        assert "world" in out and "[AI]" not in out.split("world")[0].split("\n")[-1]

    def test_no_args_prints_help(self, capsys):
        assert cli.main([]) == 0
        assert "daemon" in capsys.readouterr().out


class TestCliToggleNoDaemon:
    def test_toggle_without_daemon_errors(self, monkeypatch, capsys):
        monkeypatch.setattr(paths, "socket_path",
                            lambda: Path("/nonexistent/fluidvoice.sock"))
        assert cli.main(["toggle"]) == 1
        assert "daemon not running" in capsys.readouterr().err


class TestHotkeyListenerConstruction:
    def test_cancel_key_wiring(self):
        from fluidvoice.hotkey import HotkeyListener
        listener = HotkeyListener("F9", [], "toggle", on_toggle=lambda: None,
                                  on_cancel=lambda: None, cancel_key="Escape")
        assert listener.cancel_key == "Escape"

    def test_cancel_key_resolution(self):
        from fluidvoice.hotkey import HotkeyListener
        # omitted and "" both mean the macOS default (old templates wrote ""
        # into saved configs - they must not silently lose Escape on upgrade)
        assert HotkeyListener("F9", [], "toggle", on_toggle=lambda: None)._resolve_cancel() == "Escape"
        assert HotkeyListener("F9", [], "toggle", on_toggle=lambda: None,
                              cancel_key="")._resolve_cancel() == "Escape"
        assert HotkeyListener("F9", [], "toggle", on_toggle=lambda: None,
                              cancel_key="none")._resolve_cancel() == ""
        assert HotkeyListener("F9", [], "toggle", on_toggle=lambda: None,
                              cancel_key="F10 ")._resolve_cancel() == "F10"

    def test_modifier_mask_summed(self):
        from fluidvoice.hotkey import HotkeyListener, MODIFIER_MASKS
        listener = HotkeyListener("space", ["ctrl", "shift"], "hold", on_toggle=lambda: None)
        assert listener._mods == MODIFIER_MASKS["ctrl"] | MODIFIER_MASKS["shift"]

    def test_set_recording_toggles_cancel_grab_state(self):
        from fluidvoice.hotkey import HotkeyListener
        listener = HotkeyListener("F9", [], "toggle", on_toggle=lambda: None,
                                  cancel_key="Escape")
        assert listener._want_cancel is False
        listener.set_recording(True)
        assert listener._want_cancel is True
        listener.set_recording(False)
        assert listener._want_cancel is False

    def test_config_cancel_key_defaults_to_escape(self):
        from fluidvoice.config import DEFAULTS
        assert DEFAULTS["hotkey"]["cancel_key"] == "Escape"
