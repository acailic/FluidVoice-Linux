import json
import sys
import threading
from pathlib import Path

import pytest

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


class TestDoctorWhispercpp:
    """_whispercpp_lines resolution report (pure function, faked binary)."""

    def lines(self, model_value="", binary="/usr/bin/whisper-cli"):
        from fluidvoice import doctor
        self.monkeypatch.setattr(doctor.backends, "_whispercpp_binary",
                                 lambda: binary)
        cfg = {"model": {"whispercpp_model": model_value}}
        return doctor._whispercpp_lines(cfg)

    @pytest.fixture(autouse=True)
    def _cache(self, tmp_path, monkeypatch):
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def test_binary_missing_and_model_unset(self):
        lines = self.lines(model_value="", binary=None)
        assert any("not found" in l for l in lines)
        assert any("not set" in l for l in lines)

    def test_catalog_name_downloaded(self, tmp_path):
        from fluidvoice import model_catalog
        model_catalog.gguf_dir().mkdir(parents=True)
        model_catalog.gguf_path("ggml-base.bin").write_bytes(b"x")
        lines = self.lines(model_value="ggml-base.bin")
        assert any("downloaded" in l and "ggml-base.bin" in l for l in lines)
        assert any(str(model_catalog.gguf_path("ggml-base.bin")) in l
                   for l in lines)

    def test_catalog_name_not_downloaded(self):
        lines = self.lines(model_value="ggml-base.bin")
        assert any("not downloaded" in l for l in lines)
        assert any("downloaded ggml models: none" in l for l in lines)

    def test_path_value_found_and_missing(self, tmp_path):
        p = tmp_path / "m.bin"
        p.write_bytes(b"x")
        assert any("found" in l for l in self.lines(model_value=str(p)))
        missing = tmp_path / "gone.bin"
        assert any("MISSING" in l for l in self.lines(model_value=str(missing)))

    def test_unknown_bare_name_lists_catalog(self):
        lines = self.lines(model_value="ggml-bogus.bin")
        assert any("unknown name" in l and "ggml-base.bin" in l
                   for l in lines)


class TestDoctorParakeet:
    """_parakeet_lines resolution report (onnxruntime stubbed via sys.modules)."""

    @pytest.fixture(autouse=True)
    def _cache(self, tmp_path, monkeypatch):
        self.monkeypatch = monkeypatch
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def lines(self, backend="", name="", downloaded=lambda n: False):
        from fluidvoice import doctor, model_catalog
        self.monkeypatch.setattr(model_catalog, "parakeet_downloaded",
                                 downloaded)
        cfg = {"model": {"backend": backend, "name": name}}
        return doctor._parakeet_lines(cfg)

    def test_not_installed(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "onnxruntime", None)
        lines = self.lines()
        assert len(lines) == 1
        assert "not installed" in lines[0]
        assert "pip install onnxruntime" in lines[0]

    def test_installed_models_not_downloaded(self):
        from fluidvoice import model_catalog
        lines = self.lines()
        assert any("onnxruntime" in l for l in lines)
        for name in model_catalog.PARAKEET_CATALOG:
            assert any(name in l and "not downloaded" in l and
                       "joiner.int8.onnx" in l for l in lines), name

    def test_configured_and_downloaded(self):
        lines = self.lines(backend="parakeet", name="parakeet-tdt-0.6b-v3",
                           downloaded=lambda n: n == "parakeet-tdt-0.6b-v3")
        assert any("parakeet-tdt-0.6b-v3: downloaded" in l for l in lines)
        assert any("active model: parakeet-tdt-0.6b-v3 (downloaded)"
                   for l in lines)

    def test_configured_missing_file(self, tmp_path):
        d = tmp_path / "sayit-ermano" / "models" / "parakeet" \
            / "parakeet-tdt-0.6b-v2"
        d.mkdir(parents=True)
        for f in ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"):
            (d / f).write_bytes(b"x")
        lines = self.lines(backend="parakeet", name="parakeet-tdt-0.6b-v2")
        assert any("missing: joiner.int8.onnx" in l for l in lines)
        assert any("active model: parakeet-tdt-0.6b-v2 (not downloaded)"
                   for l in lines)

    def test_configured_unknown_name_lists_catalog(self):
        lines = self.lines(backend="parakeet", name="parakeet-t5")
        assert any("unknown name 'parakeet-t5'" in l
                   and "parakeet-tdt-0.6b-v2" in l for l in lines)


class TestDoctorFormattingLines:
    """_formatting_lines: one resolution line per new formatting key."""

    def test_defaults_on(self):
        from fluidvoice import doctor
        lines = doctor._formatting_lines(DEFAULTS)
        assert len(lines) == 3
        assert any("slash/mention squeeze: on" in l
                   and "processing.slash_mention_squeeze" in l for l in lines)
        assert any("terminal autocomplete space: on" in l
                   and "insertion.terminal_autocomplete_space" in l
                   for l in lines)
        apps = DEFAULTS["general"]["terminal_apps"]
        apps_line = next(l for l in lines if "terminal_apps" in l)
        assert f"terminal_apps ({len(apps)})" in apps_line
        assert "kitty" in apps_line and "spoken-send Enter suppressed" in apps_line

    def test_disabled_shows_off(self):
        import copy
        from fluidvoice import doctor
        cfg = copy.deepcopy(DEFAULTS)
        cfg["processing"]["slash_mention_squeeze"] = False
        cfg["insertion"]["terminal_autocomplete_space"] = False
        lines = doctor._formatting_lines(cfg)
        assert any("slash/mention squeeze: off" in l for l in lines)
        assert any("terminal autocomplete space: off" in l for l in lines)

    def test_empty_list_counts_zero(self):
        import copy
        from fluidvoice import doctor
        cfg = copy.deepcopy(DEFAULTS)
        cfg["general"]["terminal_apps"] = []
        lines = doctor._formatting_lines(cfg)
        assert any("terminal_apps (0)" in l and "none" in l for l in lines)


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
