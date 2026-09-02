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

    def test_history_page_served(self, server):
        w, port = server
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/history",
                                    timeout=5) as r:
            html = r.read().decode()
        assert "FluidVoice History" in html and "/api/history" in html

    def test_history_search_and_delete_and_clear(self, server):
        from fluidvoice import history
        w, port = server
        history.append({"ts": 1, "text": "hello world"})
        history.append({"ts": 2, "text": "grocery list", "app": "Firefox"})
        found = get(port, "/api/history?q=grocery")
        assert len(found) == 1 and found[0]["text"] == "grocery list"
        assert get(port, "/api/history?q=zzz") == []
        resp = post(port, "/api/history/delete", {"ts": 2})
        assert resp["removed"] == 1
        assert get(port, "/api/history?q=grocery") == []
        assert len(get(port, "/api/history")) == 1  # ts=1 still there
        resp = post(port, "/api/history/clear", {})
        assert resp["removed"] == 1
        assert get(port, "/api/history") == []

    def test_history_audio_requires_retained_file(self, server, tmp_path,
                                                   monkeypatch):
        w, port = server
        import wave as wav_mod
        from fluidvoice import history

        adir = tmp_path / "audio"
        adir.mkdir(exist_ok=True)
        monkeypatch.setattr(history.paths, "audio_dir", lambda: adir)
        wav = tmp_path / "utt.wav"
        with wav_mod.open(str(wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00\x00" * 1600)
        history.append({"ts": 5, "text": "with audio"},
                       audio_src=wav, keep_audio=True)
        entries = get(port, "/api/history")
        assert entries and entries[-1].get("audio")
        # serve by ts, and only files inside the audio dir
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/history/audio?ts=5",
                timeout=5) as r:
            assert r.headers["Content-Type"] == "audio/wav"
            data = r.read()
        assert len(data) > 1000
        try:
            get(port, "/api/history/audio?ts=999")
            assert False
        except urllib.error.HTTPError as e:  # noqa: F821
            assert e.code == 404

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



class TestWebUISecurity:
    """CSRF / DNS-rebinding / abuse guards (audit findings C1, C2, M4, M6)."""

    def _raw_post(self, port, path, headers, data=b"{}"):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _raw_get(self, port, path, headers):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_cross_site_origin_post_rejected(self, server):
        w, port = server
        status, body = self._raw_post(
            port, "/api/config",
            {"Host": f"127.0.0.1:{port}", "Origin": "https://evil.example",
             "Content-Type": "application/json"},
            data=json.dumps({"hotkey": {"key": "F9"}}).encode())
        assert status == 403
        assert w.cfg["hotkey"]["key"] != "F9"  # nothing was applied

    def test_same_origin_post_allowed(self, server):
        w, port = server
        status, _ = self._raw_post(
            port, "/api/config",
            {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}",
             "Content-Type": "application/json"},
            data=json.dumps({"hotkey": {"key": "F7"}}).encode())
        assert status == 200 and w.cfg["hotkey"]["key"] == "F7"

    def test_foreign_host_rejected_get(self, server):
        # DNS rebinding: attacker.com resolves here, sends Host: attacker.com
        w, port = server
        status, _ = self._raw_get(port, "/api/history", {"Host": "attacker.com"})
        assert status == 403

    def test_post_requires_json_content_type(self, server):
        w, port = server
        status, _ = self._raw_post(
            port, "/api/config",
            {"Host": f"127.0.0.1:{port}", "Content-Type": "text/plain"},
            data=json.dumps({"hotkey": {"key": "F6"}}).encode())
        assert status == 403

    def test_oversized_body_rejected(self, server):
        w, port = server
        big = b"x" * (200 * 1024)
        status, _ = self._raw_post(
            port, "/api/config",
            {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json",
             "Content-Length": str(len(big))},
            data=big)
        assert status == 413

    def test_test_ai_hides_key_from_foreign_host(self, server, monkeypatch):
        captured = {}

        class FakeClient:
            configured = True

            def __init__(self, cfg):
                captured["base_url"] = cfg["ai"]["base_url"]
                captured["api_key"] = cfg["ai"].get("api_key", "")

            def chat(self, msg):
                return "ok"

        monkeypatch.setattr(webui, "AIClient", FakeClient)
        w, port = server
        w.cfg["ai"]["api_key"] = "sk-secret"
        resp = post(port, "/api/test-ai",
                    {"base_url": "https://attacker.example/v1", "model": "m"})
        assert resp["ok"]
        assert captured["api_key"] == ""  # key never sent to a foreign host
        assert captured["base_url"] == "https://attacker.example/v1"

    def test_test_ai_keeps_key_for_saved_host(self, server, monkeypatch):
        captured = {}

        class FakeClient:
            configured = True

            def __init__(self, cfg):
                captured["api_key"] = cfg["ai"].get("api_key", "")

            def chat(self, msg):
                return "ok"

        monkeypatch.setattr(webui, "AIClient", FakeClient)
        w, port = server
        w.cfg["ai"]["api_key"] = "sk-secret"
        w.cfg["ai"]["base_url"] = "http://localhost:11434/v1"
        post(port, "/api/test-ai", {"base_url": "http://localhost:11434/v1",
                                    "model": "m"})
        assert captured["api_key"] == "sk-secret"

    def test_config_validation_rejects_garbage(self, server):
        w, port = server
        resp = post(port, "/api/config",
                    {"recording": {"max_seconds": "abc"},
                     "insertion": {"type_delay_ms": "8; rm"},
                     "hotkey": {"mode": "explode"}})
        assert sorted(resp["rejected"]) == ["hotkey.mode",
                                            "insertion.type_delay_ms",
                                            "recording.max_seconds"]
        assert w.cfg["recording"]["max_seconds"] != "abc"

    def test_config_rejects_dash_prefixed_strings(self, server):
        w, port = server
        resp = post(port, "/api/config", {"hotkey": {"key": "--injection"}})
        assert "hotkey.key" in resp["rejected"]

    def test_warmup_failure_rolls_back_model(self, server, monkeypatch):
        import time as _time

        def boom(cfg):
            raise RuntimeError("download failed")

        monkeypatch.setattr(webui.backends, "load_backend", boom)
        w, port = server
        before = w.cfg["model"]["name"]
        post(port, "/api/models/select", {"name": "medium"})
        deadline = _time.monotonic() + 5
        while w.warmup["running"] and _time.monotonic() < deadline:
            _time.sleep(0.05)
        assert w.warmup["error"] == "download failed"
        assert w.cfg["model"]["name"] == before  # rolled back

    def test_warmup_double_spawn_rejected(self, server, monkeypatch):
        import time as _time
        release = _time.monotonic() + 1.5

        class SlowBackend:
            name = "slow"

            def warmup(self):
                while _time.monotonic() < release:
                    _time.sleep(0.05)

        monkeypatch.setattr(webui.backends, "load_backend",
                            lambda c: SlowBackend())
        w, port = server
        assert post(port, "/api/models/select", {"name": "tiny"})["ok"]
        second = post(port, "/api/models/select", {"name": "base"})
        assert not second["ok"] and "already running" in second["error"]


class TestConfigPermissions:
    def test_saved_config_is_0600(self, tmp_path, monkeypatch):
        import os
        from fluidvoice import paths as p
        target = tmp_path / "c.toml"
        monkeypatch.setattr(p, "config_file", lambda: target)
        save_config(copy.deepcopy(DEFAULTS))
        assert os.stat(target).st_mode & 0o777 == 0o600

    def test_write_template_is_0600(self, tmp_path, monkeypatch):
        import os
        from fluidvoice import paths as p
        from fluidvoice.config import write_template
        target = tmp_path / "c.toml"
        monkeypatch.setattr(p, "config_file", lambda: target)
        write_template()
        assert os.stat(target).st_mode & 0o777 == 0o600
