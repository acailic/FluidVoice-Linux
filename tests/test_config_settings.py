"""Config persistence + the settings validation layer (apply_settings).

Migrated from the retired web UI's test suite (test_webui.py): the
save/permission tests were always config-level; the validator tests keep
guarding the same semantics through the one source of truth the daemon's
set-config socket action uses.
"""
from __future__ import annotations

import copy
import os

import pytest

from fluidvoice.config import (DEFAULTS, RESTART_REQUIRED, TEMPLATE,
                               apply_settings, coerce_setting, load_config,
                               save_config)


class TestSaveConfig:
    def test_roundtrip(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        monkeypatch.setattr(p, "config_file", lambda: tmp_path / "c.toml")
        cfg = copy.deepcopy(DEFAULTS)
        cfg["hotkey"]["key"] = "F9"
        cfg["ai"]["enabled"] = True
        cfg["processing"]["dictionary"] = [
            {"triggers": ["fluid voice"], "replacement": "FluidVoice"}]
        save_config(cfg)
        loaded = load_config(tmp_path / "c.toml")
        assert loaded["hotkey"]["key"] == "F9"
        assert loaded["ai"]["enabled"] is True
        assert loaded["processing"]["dictionary"][0]["triggers"] == ["fluid voice"]

    def test_api_key_carried_over(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        target = tmp_path / "c.toml"
        target.write_text('[ai]\napi_key = "sk-secret"\nenabled = false\n')
        monkeypatch.setattr(p, "config_file", lambda: target)
        cfg = copy.deepcopy(DEFAULTS)
        cfg["ai"]["enabled"] = True
        save_config(cfg)
        text = target.read_text()
        assert 'api_key = "sk-secret"' in text  # not lost by the save
        assert "enabled = true" in text

    def test_special_characters_escaped(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        target = tmp_path / "c.toml"
        monkeypatch.setattr(p, "config_file", lambda: target)
        cfg = copy.deepcopy(DEFAULTS)
        cfg["processing"]["punctuation_prefix"] = 'we"ird\\prefix'
        save_config(cfg)
        assert load_config(target)["processing"]["punctuation_prefix"] == 'we"ird\\prefix'

    def test_retired_server_section_stripped(self, tmp_path):
        target = tmp_path / "old.toml"
        target.write_text('[server]\nport = 47735\nenabled = true\n'
                          '[sounds]\nenabled = false\n')
        cfg = load_config(target)
        assert "server" not in cfg  # old configs carry it; loader drops it
        assert cfg["sounds"]["enabled"] is False  # other sections unaffected


class TestConfigPermissions:
    def test_saved_config_is_0600(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        target = tmp_path / "c.toml"
        monkeypatch.setattr(p, "config_file", lambda: target)
        save_config(copy.deepcopy(DEFAULTS))
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_write_template_is_0600(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        from fluidvoice.config import write_template
        target = tmp_path / "c.toml"
        monkeypatch.setattr(p, "config_file", lambda: target)
        write_template()
        assert os.stat(target).st_mode & 0o777 == 0o600


@pytest.fixture()
def cfg():
    return copy.deepcopy(DEFAULTS)


class TestApplySettings:
    def test_full_surface_roundtrip(self, cfg):
        changed, rejected = apply_settings(cfg, {
            "recording": {"preview_overlay_size": "large",
                          "preview_bottom_offset": 128,
                          "spoken_send_enabled": True,
                          "spoken_send_phrase": "send it now",
                          "spoken_send_key": "shift+enter",
                          "pause_media": False},
            "hotkey": {"rewrite_key": "F8", "modifiers": ["ctrl"]},
            "general": {"tray_enabled": False},
            "model": {"eager_warmup": False},
            "processing": {"gaav_enabled": True},
        })
        assert rejected == [] and len(changed) == 11
        assert cfg["recording"]["preview_overlay_size"] == "large"
        assert cfg["hotkey"]["rewrite_key"] == "F8"
        assert cfg["model"]["eager_warmup"] is False

    def test_garbage_rejected_nothing_half_applied(self, cfg):
        before = copy.deepcopy(cfg)
        changed, rejected = apply_settings(cfg, {
            "recording": {"max_seconds": "abc"},
            "insertion": {"type_delay_ms": "8; rm"},
            "hotkey": {"mode": "explode"},
            "sounds": {"volume": 0.5},
        })
        assert sorted(rejected) == ["hotkey.mode",
                                    "insertion.type_delay_ms",
                                    "recording.max_seconds"]
        assert changed == ["sounds.volume"]  # the valid one still applies
        assert cfg["recording"]["max_seconds"] == before["recording"]["max_seconds"]

    def test_unknown_and_retired_sections_ignored(self, cfg):
        changed, rejected = apply_settings(cfg, {
            "server": {"port": 1}, "nope": {"x": 1},
            "ai": {"api_key": "should-not-set"}})
        assert changed == [] and rejected == []

    def test_per_app_prompts_validated(self, cfg):
        ok_rules = [{"apps": ["zed"], "instructions": "be terse"}]
        changed, rejected = apply_settings(
            cfg, {"ai": {"per_app_prompts": ok_rules}})
        assert rejected == [] and cfg["ai"]["per_app_prompts"] == ok_rules
        for bad in ("nope", [{"apps": [], "instructions": "x"}],
                    [{"apps": ["a"], "instructions": ""}]):
            _, rejected = apply_settings(
                cfg, {"ai": {"per_app_prompts": bad}})
            assert rejected == ["ai.per_app_prompts"], bad
        # over-long instructions are truncated (webui-endpoint semantics)
        _, rejected = apply_settings(
            cfg, {"ai": {"per_app_prompts":
                         [{"apps": ["a"], "instructions": "x" * 3000}]}})
        assert rejected == []
        assert len(cfg["ai"]["per_app_prompts"][0]["instructions"]) == 2000

    def test_model_name_aliasing(self, cfg):
        changed, rejected = apply_settings(cfg, {"model": {"name": "turbo"}})
        assert rejected == [] and cfg["model"]["name"] == "large-v3-turbo"
        _, rejected = apply_settings(cfg, {"model": {"name": "gpt-4o"}})
        assert rejected == ["model.name"]

    def test_restart_required_is_only_model_warmup_now(self):
        # the [server] section retired with the web UI
        assert RESTART_REQUIRED == {"model.eager_warmup"}


class TestMicPriority:
    """recording.mic_priority: ordered patterns for auto mic switching."""

    def test_defaults_and_template_documented(self):
        assert DEFAULTS["recording"]["mic_priority"] == []
        assert "mic_priority" in TEMPLATE  # cheap doc-guard

    def test_clean_strips_empties_and_keeps_order(self):
        ok, cleaned = coerce_setting(
            "recording", "mic_priority", [" bluez ", "", "USB-Cam"])
        assert ok is True and cleaned == ["bluez", "USB-Cam"]

    def test_dedupes_case_insensitively_first_wins(self):
        ok, cleaned = coerce_setting(
            "recording", "mic_priority", ["BlueZ", "bluez", " BLUEZ "])
        assert ok is True and cleaned == ["BlueZ"]

    @pytest.mark.parametrize("bad", [
        "bluez",            # not a list
        [42],                # non-str entry
        ["x" * 65],          # single entry over 64 chars
        [f"p{i}" for i in range(21)],  # 21 entries (max 20)
    ])
    def test_rejects_bad_values(self, bad):
        ok, out = coerce_setting("recording", "mic_priority", bad)
        assert ok is False and out == bad

    def test_twenty_entries_accepted(self):
        ok, cleaned = coerce_setting(
            "recording", "mic_priority", [f"p{i}" for i in range(20)])
        assert ok is True and len(cleaned) == 20

    def test_empty_list_is_valid(self):
        ok, cleaned = coerce_setting("recording", "mic_priority", [])
        assert ok is True and cleaned == []

    def test_apply_settings_applies_and_reports(self, cfg):
        changed, rejected = apply_settings(
            cfg, {"recording": {"mic_priority": ["bluez"]}})
        assert rejected == [] and "recording.mic_priority" in changed
        assert cfg["recording"]["mic_priority"] == ["bluez"]

    def test_save_whitelist_roundtrip(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        monkeypatch.setattr(p, "config_file", lambda: tmp_path / "c.toml")
        cfg = copy.deepcopy(DEFAULTS)
        cfg["recording"]["mic_priority"] = ["bluez", "usb-cam"]
        save_config(cfg)
        loaded = load_config(tmp_path / "c.toml")
        assert loaded["recording"]["mic_priority"] == ["bluez", "usb-cam"]


class TestCommandSettings:
    """Command mode keys: hotkey.command_key + the [command] section."""

    def test_defaults(self, cfg):
        assert cfg["hotkey"]["command_key"] == ""
        assert cfg["command"] == {"max_turns": 4, "working_dir": "",
                                  "timeout_seconds": 60.0,
                                  "confirm_timeout_s": 120.0}

    def test_apply_accepts_command_keys(self, cfg):
        changed, rejected = apply_settings(cfg, {
            "hotkey": {"command_key": "F9"},
            "command": {"max_turns": 6, "working_dir": "/tmp",
                        "timeout_seconds": 30, "confirm_timeout_s": 60},
        })
        assert rejected == []
        assert set(changed) == {"hotkey.command_key", "command.max_turns",
                                "command.working_dir",
                                "command.timeout_seconds",
                                "command.confirm_timeout_s"}
        assert cfg["hotkey"]["command_key"] == "F9"
        assert cfg["command"]["max_turns"] == 6
        assert cfg["command"]["working_dir"] == "/tmp"
        assert cfg["command"]["timeout_seconds"] == 30.0
        assert cfg["command"]["confirm_timeout_s"] == 60.0

    def test_apply_rejects_bad_values(self, cfg):
        before = copy.deepcopy(cfg["command"])
        _, rejected = apply_settings(cfg, {
            "command": {"max_turns": 0, "working_dir": "x" * 5000,
                        "timeout_seconds": 0}})
        _, rejected2 = apply_settings(cfg, {
            "command": {"max_turns": 21}})
        _, rejected3 = apply_settings(cfg, {
            "command": {"max_turns": "four"}})
        assert "command.max_turns" in rejected  # 0
        assert "command.working_dir" in rejected
        assert "command.timeout_seconds" in rejected
        assert "command.max_turns" in rejected2  # 21
        assert "command.max_turns" in rejected3  # "four"
        assert cfg["command"] == before  # untouched

    def test_save_whitelist_writes_command_section(self, tmp_path, monkeypatch):
        from fluidvoice import paths as p
        monkeypatch.setattr(p, "config_file", lambda: tmp_path / "c.toml")
        cfg = copy.deepcopy(DEFAULTS)
        cfg["hotkey"]["command_key"] = "F9"
        cfg["command"].update(max_turns=6, working_dir="/tmp",
                              timeout_seconds=30, confirm_timeout_s=60)
        save_config(cfg)
        text = (tmp_path / "c.toml").read_text()
        assert "[command]" in text
        assert "command_key = \"F9\"" in text
        assert "max_turns = 6" in text
        loaded = load_config(tmp_path / "c.toml")
        assert loaded["command"] == {"max_turns": 6, "working_dir": "/tmp",
                                     "timeout_seconds": 30.0,
                                     "confirm_timeout_s": 60.0}
