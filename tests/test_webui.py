from __future__ import annotations

import json
import copy
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from fluidvoice import webui
from fluidvoice.config import DEFAULTS, load_config, save_config


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


class FakeDaemon:
    def __init__(self):
        self.backend = None
        self.toggled = 0

    def handle_request(self, req):
        if req["action"] == "status":
            return {"ok": True, "recording": False, "busy": False, "backend": "stub"}
        if req["action"] == "toggle":
            self.toggled += 1
            return {"ok": True, "recording": self.toggled % 2 == 1}
        return {"ok": False}


@pytest.fixture()
def server(tmp_path, monkeypatch):
    """WebUI on an ephemeral port with tmp config + history."""
    from fluidvoice import history
    monkeypatch.setattr(webui.paths, "config_file", lambda: tmp_path / "c.toml")
    monkeypatch.setattr(webui.paths, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(webui.paths, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(history.paths, "history_file", lambda: tmp_path / "h.jsonl")
    cfg = copy.deepcopy(DEFAULTS)
    cfg["server"]["port"] = 0  # ephemeral
    w = webui.WebUI(daemon=FakeDaemon(), cfg=cfg)
    port = w.start()
    yield w, port
    w.stop()


def get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read())


def post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class TestWebUIAPI:
    def test_serves_page(self, server):
        w, port = server
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            html = r.read().decode()
        assert "FluidVoice" in html and "Speech models" in html

    def test_status(self, server):
        w, port = server
        s = get(port, "/api/status")
        assert s["backend"] == "stub" and s["recording"] is False
        assert s["active_model"] in webui.MODEL_CATALOG

    def test_models_catalog(self, server):
        w, port = server
        models = {m["name"]: m for m in get(port, "/api/models")}
        assert set(models) == set(webui.MODEL_CATALOG)
        assert models["small"]["active"] is True  # DEFAULTS -> auto -> small (cuda here)
        assert all("size" in m for m in models.values())

    def test_select_model_updates_config_and_file(self, server, monkeypatch):
        import time as _time

        class FakeWarmable:
            name = "faster-whisper"

            def warmup(self):
                pass

        monkeypatch.setattr(webui.backends, "load_backend", lambda c: FakeWarmable())
        w, port = server
        resp = post(port, "/api/models/select", {"name": "turbo"})
        assert resp["ok"] and resp["model"] == "large-v3-turbo"
        assert w.cfg["model"]["name"] == "large-v3-turbo"
        deadline = _time.monotonic() + 5
        while w.warmup["running"] and _time.monotonic() < deadline:
            _time.sleep(0.05)
        assert w.warmup["error"] is None
        assert w.daemon.backend.name == "faster-whisper"  # hot-swapped into daemon

    def test_select_unknown_model_rejected(self, server):
        w, port = server
        resp = post(port, "/api/models/select", {"name": "gpt-4o"})
        assert resp["ok"] is False

    def test_config_get_masks_api_key(self, server):
        w, port = server
        w.cfg["ai"]["api_key"] = "sk-supersecret"
        c = get(port, "/api/config")
        assert c["ai"]["api_key"] is True
        assert "supersecret" not in json.dumps(c)

    def test_config_post_whitelist(self, server):
        w, port = server
        resp = post(port, "/api/config", {"hotkey": {"key": "F9"},
                                          "ai": {"enabled": True, "api_key": "nope"}})
        assert resp["ok"] and "hotkey.key" in resp["changed"]
        assert w.cfg["hotkey"]["key"] == "F9"
        assert "api_key" not in str(resp["changed"])
        assert "api_key" not in w.cfg["ai"] or w.cfg["ai"]["api_key"] != "nope"

    def test_history_endpoint(self, server, tmp_path):
        from fluidvoice import history
        w, port = server
        history.append({"ts": 1, "text": "entry one"})
        entries = get(port, "/api/history")
        assert entries and entries[-1]["text"] == "entry one"

    def test_toggle_passes_to_daemon(self, server):
        w, port = server
        resp = post(port, "/api/toggle", {})
        assert resp["ok"] and w.daemon.toggled == 1

    def test_unknown_route_404(self, server):
        w, port = server
        try:
            get(port, "/api/nope")
            assert False
        except urllib.error.HTTPError as e:  # noqa: F821
            assert e.code == 404


class TestModelDownloaded:
    def test_missing_repo_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(webui.paths, "models_dir", lambda: tmp_path / "m")
        monkeypatch.setattr(webui.paths, "cache_dir", lambda: tmp_path / "cache")
        assert webui.model_downloaded("small") is False

    def test_existing_cache_true(self, tmp_path, monkeypatch):
        monkeypatch.setattr(webui.paths, "models_dir", lambda: tmp_path / "m")
        monkeypatch.setattr(webui.paths, "cache_dir", lambda: tmp_path / "cache")
        repo_dir = tmp_path / "m" / "faster-whisper" / "models--Systran--faster-whisper-small"
        repo_dir.mkdir(parents=True)
        (repo_dir / "model.bin").write_bytes(b"x")
        assert webui.model_downloaded("small") is True

