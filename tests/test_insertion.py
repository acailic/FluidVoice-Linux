from __future__ import annotations

import subprocess

import pytest

from fluidvoice import insertion


def ok(args=None, stdout=b""):
    return subprocess.CompletedProcess(args or [], 0, stdout, b"")


@pytest.fixture()
def runner(monkeypatch):
    """Capture subprocess calls made through insertion._run."""
    calls: dict = {"run": [], "popen": []}

    def fake_run(args, timeout=15.0, stdin=None):
        calls["run"].append(list(args))
        if args[0] == "xclip" and "-o" in args:
            return ok(args, b"previous clipboard")
        return ok(args)

    def fake_popen(args, **kwargs):
        calls["popen"].append(list(args))

        class P:
            def communicate(self, data=None):
                return (data, None)
        return P()

    monkeypatch.setattr(insertion, "_run", fake_run)
    monkeypatch.setattr(insertion.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(insertion.time, "sleep", lambda s: None)
    return calls


def base_cfg(mode="auto", threshold=1200, delay=8):
    return {"insertion": {"mode": mode, "type_delay_ms": delay,
                          "paste_threshold_chars": threshold}}


def full_cfg(mode="auto", threshold=1200, delay=8, apps=None, space=True):
    from fluidvoice.config import DEFAULTS
    import copy
    cfg = copy.deepcopy(DEFAULTS)
    cfg["insertion"].update(mode=mode, type_delay_ms=delay,
                            paste_threshold_chars=threshold,
                            terminal_autocomplete_space=space)
    if apps is not None:
        cfg["general"]["terminal_apps"] = apps
    return cfg


class TestTyped:
    def test_command_construction(self, runner):
        assert insertion.insert_text("hello world", base_cfg()) == "typed"
        cmd = next(c for c in runner["run"] if c[:2] == ["xdotool", "type"])
        assert "--clearmodifiers" in cmd
        assert cmd[cmd.index("--delay") + 1] == "8"
        assert cmd[-1] == "hello world"

    def test_leading_dash_never_typed(self, runner):
        # "-" would be parsed as an xdotool option -> must go via paste
        assert insertion.insert_text("--verbose please", base_cfg()) == "paste"

    def test_failure_raises(self, monkeypatch):
        def failing(args, timeout=15.0, stdin=None):
            return subprocess.CompletedProcess(args, 1, b"", b"boom")
        monkeypatch.setattr(insertion, "_run", failing)
        with pytest.raises(insertion.InsertError):
            insertion.insert_typed("hi", 5)


class TestPaste:
    def test_long_text_uses_paste(self, runner):
        text = "x" * 2000
        assert insertion.insert_text(text, base_cfg()) == "paste"
        # clipboard was written with the text, ctrl+v sent, previous restored
        writes = [c for c in runner["popen"] if c[0] == "xclip"]
        assert writes, "xclip must be used"
        keys = [c for c in runner["run"] if c[:2] == ["xdotool", "key"]]
        assert keys and "ctrl+v" in keys[0]

    def test_paste_mode_restores_clipboard(self, runner):
        insertion.insert_text("typed via clipboard", base_cfg(mode="paste"))
        # two xclip writes: text then restore of "previous clipboard"
        assert len([c for c in runner["popen"] if c[0] == "xclip"]) == 2

    def test_paste_failure_in_auto_mode_falls_back_to_typed(self, runner, monkeypatch):
        def run_no_xdotool_key(args, timeout=15.0, stdin=None):
            if args[:2] == ["xdotool", "key"]:
                return subprocess.CompletedProcess(args, 1, b"", b"no key")
            return ok(args)
        monkeypatch.setattr(insertion, "_run", run_no_xdotool_key)
        # long text chooses paste in auto mode; failure falls back to typed
        assert insertion.insert_text("x" * 2000, base_cfg()) == "typed"

    def test_paste_failure_in_paste_mode_raises(self, runner, monkeypatch):
        def run_no_xdotool_key(args, timeout=15.0, stdin=None):
            if args[:2] == ["xdotool", "key"]:
                return subprocess.CompletedProcess(args, 1, b"", b"no key")
            return ok(args)
        monkeypatch.setattr(insertion, "_run", run_no_xdotool_key)
        with pytest.raises(insertion.InsertError):
            insertion.insert_text("short", base_cfg(mode="paste"))

    def test_missing_xclip_raises(self, monkeypatch):
        monkeypatch.setattr(insertion.shutil, "which", lambda n: None)
        with pytest.raises(insertion.InsertError):
            insertion.insert_paste("text")


class TestActiveWindowClass:
    def test_parses_wm_class(self, runner, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":99")  # hermetic: no ambient X needed
        monkeypatch.setattr(insertion.shutil, "which",
                            lambda n: "/usr/bin/" + n if n in ("xdotool", "xprop") else None)

        def fake_run(args, timeout=15.0, stdin=None):
            if args[0] == "xdotool":
                return ok(args, b"12345\n")
            return ok(args, b'WM_CLASS(STRING) = "instance", "dev.warp.Warp"\n')

        monkeypatch.setattr(insertion, "_run", fake_run)
        assert insertion.active_window_class() == "dev.warp.Warp"

    def test_falls_back_to_window_name(self, runner, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":99")  # hermetic: no ambient X needed
        monkeypatch.setattr(insertion.shutil, "which",
                            lambda n: "/usr/bin/xdotool" if n == "xdotool" else None)

        def fake_run(args, timeout=15.0, stdin=None):
            if args[:2] == ["xdotool", "getwindowname"]:
                return ok(args, b"Some Window Title")
            return ok(args, b"12345\n")

        monkeypatch.setattr(insertion, "_run", fake_run)
        assert insertion.active_window_class() == "Some Window Title"

    def test_no_display(self, runner, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        assert insertion.active_window_class() is None


class TestTerminalAutocompleteSpace:
    """general.terminal_apps matching + the one-space autocomplete rule."""

    def test_class_matching(self):
        assert insertion.is_terminal_app("gnome-terminal-server", full_cfg())
        assert insertion.is_terminal_app("Kitty", full_cfg())       # case
        assert insertion.is_terminal_app("GHOSTTY", full_cfg())     # -insensitive
        assert insertion.is_terminal_app("org.wezfurlong.wezterm",
                                         full_cfg())                  # substring
        assert not insertion.is_terminal_app("firefox", full_cfg())
        assert not insertion.is_terminal_app(None, full_cfg())
        assert not insertion.is_terminal_app("", full_cfg())

    def test_custom_list_honored(self):
        cfg = full_cfg(apps=["contour"])
        assert insertion.is_terminal_app("Contour Term", cfg)
        assert not insertion.is_terminal_app("kitty", cfg)

    def test_empty_list_matches_nothing(self):
        cfg = full_cfg(apps=[])
        assert not insertion.is_terminal_app("kitty", cfg)

    def test_trailing_space_helper(self):
        assert insertion.terminal_trailing_space("git checkout") \
            == "git checkout "
        assert insertion.terminal_trailing_space("done.") == "done."
        assert insertion.terminal_trailing_space("already ") == "already "
        assert insertion.terminal_trailing_space("") == ""

    def test_typed_text_in_terminal_gains_space(self, runner):
        assert insertion.insert_text("git checkout", full_cfg(),
                                     wm_class="kitty") == "typed"
        cmd = runner["run"][0]
        assert cmd[-1] == "git checkout "  # trailing space committed

    def test_punctuation_ending_no_space(self, runner):
        insertion.insert_text("done.", full_cfg(), wm_class="kitty")
        assert runner["run"][0][-1] == "done."

    def test_already_spaced_idempotent(self, runner):
        insertion.insert_text("already ", full_cfg(), wm_class="kitty")
        assert runner["run"][0][-1] == "already "

    def test_paste_path_never_gains_space(self, runner):
        assert insertion.insert_text("x" * 2000, full_cfg(),
                                     wm_class="kitty") == "paste"
        writes = [c for c in runner["popen"] if c[0] == "xclip"]
        assert writes and writes[0][-1] is not None  # clipboard used
        typed = [c for c in runner["run"] if c[:2] == ["xdotool", "type"]]
        assert typed == []  # nothing typed, nothing spaced

    def test_disabled_by_config(self, runner):
        insertion.insert_text("git checkout", full_cfg(space=False),
                              wm_class="kitty")
        assert runner["run"][0][-1] == "git checkout"

    def test_non_terminal_app_no_space(self, runner):
        insertion.insert_text("git checkout", full_cfg(), wm_class="firefox")
        assert runner["run"][0][-1] == "git checkout"

    def test_none_wm_class_resolved_live(self, runner, monkeypatch):
        monkeypatch.setattr(insertion, "active_window_class", lambda: "kitty")
        insertion.insert_text("git checkout", full_cfg())
        assert runner["run"][0][-1] == "git checkout "

    def test_none_wm_class_headless_no_lookup_crash(self, runner, monkeypatch):
        monkeypatch.setattr(insertion, "active_window_class", lambda: None)
        insertion.insert_text("git checkout", full_cfg())
        assert runner["run"][0][-1] == "git checkout"


class TestClipboardFallback:
    def test_writes_when_xclip_exists(self, runner):
        insertion.clipboard_fallback("emergency text")
        assert any(c[0] == "xclip" for c in runner["popen"])

    def test_silent_without_xclip(self, runner, monkeypatch):
        monkeypatch.setattr(insertion.shutil, "which", lambda n: None)
        insertion.clipboard_fallback("emergency")  # must not raise
