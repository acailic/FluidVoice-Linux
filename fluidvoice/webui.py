"""Local settings web UI (127.0.0.1 only) - the Linux counterpart of the
macOS app's settings window: model picker, AI config, processing toggles,
history. Zero dependencies: stdlib http.server + one embedded page.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__, backends, history as history_mod, paths
from .ai.client import AIClient, AIError
from .config import load_config, save_config

# name -> (display size, languages, note)
MODEL_CATALOG: dict[str, dict[str, str]] = {
    "tiny": {"size": "~75 MB", "langs": "99", "note": "fastest, lowest accuracy"},
    "base": {"size": "~145 MB", "langs": "99", "note": "fast; CPU default"},
    "small": {"size": "~484 MB", "langs": "99", "note": "balanced; GPU default"},
    "medium": {"size": "~1.5 GB", "langs": "99", "note": "accurate, heavier"},
    "large-v3": {"size": "~2.9 GB", "langs": "99", "note": "best accuracy"},
    "large-v3-turbo": {"size": "~1.6 GB", "langs": "99", "note": "near-large quality, faster"},
}


def model_downloaded(name: str) -> bool:
    """Best-effort check of the faster-whisper download cache (ignores
    in-progress .incomplete blobs)."""
    repo = backends.FW_MODEL_REPOS.get(backends.ALIASES.get(name, name), "")
    if not repo:
        return False
    for root in (paths.models_dir() / "faster-whisper",
                 paths.cache_dir().parent / "huggingface" / "hub"):
        candidate = root / ("models--" + repo.replace("/", "--"))
        if not candidate.exists():
            continue
        for blob in candidate.rglob("*"):
            if blob.is_file() and ".incomplete" not in blob.name:
                return True
    return False


class WebUI:
    """Serves the settings page + JSON API; talks to the daemon for live state."""

    def __init__(self, daemon=None, cfg: dict | None = None):
        self.daemon = daemon
        self.cfg = cfg or load_config()
        self.warmup = {"running": False, "error": None, "model": None}
        self._warmup_lock = threading.Lock()
        self._srv: ThreadingHTTPServer | None = None
        self.port = 0

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> int:
        webui = self

        class Handler(_Handler):
            webui_ref = webui

        self._srv = ThreadingHTTPServer(("127.0.0.1", int(self.cfg["server"]["port"])), Handler)
        self.port = self._srv.server_address[1]
        threading.Thread(target=self._srv.serve_forever, name="fluidvoice-webui",
                         daemon=True).start()
        return self.port

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv = None

    # -- api helpers -----------------------------------------------------------

    def api_status(self) -> dict:
        d = self.daemon
        status = d.handle_request({"action": "status"}) if d else {"recording": False, "busy": False}
        active = backends.resolve_model_name(self.cfg["model"]["name"]) \
            if str(self.cfg["model"].get("name", "auto")) in ("", "auto") \
            else backends.ALIASES.get(str(self.cfg["model"]["name"]).lower(),
                                      str(self.cfg["model"]["name"]).lower())
        return {
            "version": __version__,
            "recording": status.get("recording", False),
            "busy": status.get("busy", False),
            "backend": status.get("backend"),
            "cuda": backends.cuda_available(),
            "active_model": active,
            "warmup": dict(self.warmup),
        }

    def api_models(self) -> list[dict]:
        active = self.api_status()["active_model"]
        out = []
        for name, info in MODEL_CATALOG.items():
            out.append({"name": name, **info,
                        "active": name == active,
                        "downloaded": model_downloaded(name)})
        return out

    def api_select_model(self, name: str) -> dict:
        name = backends.ALIASES.get(name.strip().lower(), name.strip().lower())
        if name not in backends.FW_MODEL_REPOS:
            return {"ok": False, "error": f"unknown model '{name}'"}
        with self._warmup_lock:
            if self.warmup["running"]:
                return {"ok": False, "error": "a model download is already running"}
            self.warmup = {"running": True, "error": None, "model": name}
        threading.Thread(target=self._warmup_model, args=(name,), daemon=True).start()
        return {"ok": True, "model": name}

    def _warmup_model(self, name: str) -> None:
        previous = self.cfg["model"].get("name", "auto")
        try:
            cfg = dict(self.cfg)
            cfg["model"] = dict(self.cfg["model"], name=name)
            backend = backends.load_backend(cfg)
            backend.warmup()
            # Persist the choice only after the model is verified usable.
            self.cfg["model"]["name"] = name
            save_config(self.cfg)
            if self.daemon is not None:
                self.daemon.backend = backend  # hot-swap into the running daemon
            self.warmup = {"running": False, "error": None, "model": name}
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.cfg["model"]["name"] = previous  # roll back, keep the daemon usable
            self.warmup = {"running": False, "error": str(e)[:300], "model": name}

    def api_test_ai(self, body: dict) -> dict:
        from urllib.parse import urlparse
        cfg = dict(self.cfg)
        ai = dict(self.cfg["ai"], **{k: v for k, v in body.items()
                                     if k in ("enabled", "base_url", "model")})
        ai["enabled"] = True
        # Never attach the stored/env API key to a host the user has not saved:
        # this endpoint must not become a way to exfiltrate secrets elsewhere.
        tested = (ai.get("base_url") or "").rstrip("/")
        saved = (self.cfg["ai"].get("base_url") or "").rstrip("/")
        if urlparse(tested).hostname != urlparse(saved).hostname:
            ai["api_key"] = ""
            ai["api_key_env"] = ""
        cfg["ai"] = ai
        client = AIClient(cfg)
        if not client.configured:
            return {"ok": False, "error": "set base_url and model first"}
        try:
            reply = client.chat("Reply with exactly: ok")
            return {"ok": True, "reply": reply[:200]}
        except AIError as e:
            return {"ok": False, "error": str(e)[:300]}

    # -- history (the macOS main window's history list) ------------------------

    def api_history(self, q: str = "", limit: int = 100) -> list[dict]:
        limit = max(1, min(limit, 500))
        return history_mod.search(q, limit)

    def api_history_delete(self, body: dict) -> dict:
        try:
            ts = float(body.get("ts", 0))
        except (TypeError, ValueError):
            return {"ok": False, "error": "bad ts"}
        removed = history_mod.delete(ts)
        return {"ok": True, "removed": removed}

    def api_history_clear(self) -> dict:
        removed = history_mod.clear()
        return {"ok": True, "removed": removed}

    def api_config_get(self) -> dict:
        safe = json.loads(json.dumps(self.cfg))  # plain copy
        key = safe.get("ai", {}).get("api_key", "")
        safe.setdefault("ai", {})["api_key"] = bool(key)  # never leak the value
        return safe

    # Per-key coercion/validation so a garbled or hostile POST can't break the
    # dictation loop (e.g. max_seconds="abc" crashing float()).
    _VALIDATORS: dict[tuple[str, str], Any] = {
        ("recording", "first_pcm_timeout"): ("float", (0.0, 60.0)),
        ("recording", "preview_interval"): ("float", (0.3, 10.0)),
        ("recording", "preview_min_audio"): ("float", (0.3, 10.0)),
        ("recording", "preview_bottom_offset"): ("int", (0, 400)),
        ("hotkey", "key"): ("str", 64),
        ("hotkey", "cancel_key"): ("str", 64),
        ("recording", "device"): ("str", 256),
        ("recording", "max_seconds"): ("float", (1, 86400)),
        ("model", "whispercpp_model"): ("str", 4096),
        ("processing", "punctuation_prefix"): ("str", 32),
        ("ai", "base_url"): ("str", 2048),
        ("ai", "model"): ("str", 256),
        ("ai", "api_key_env"): ("str", 128),
        ("ai", "temperature"): ("float", (0.0, 2.0)),
        ("ai", "timeout_seconds"): ("float", (1, 3600)),
        ("insertion", "type_delay_ms"): ("int", (0, 1000)),
        ("insertion", "paste_threshold_chars"): ("int", (1, 1_000_000)),
        ("sounds", "volume"): ("float", (0.0, 1.0)),
        ("history", "audio_budget_gb"): ("float", (0.0, 1024.0)),
        ("server", "port"): ("int", (1024, 65535)),
    }
    _ENUMS = {("recording", "preview_mode"): {"auto", "notify", "overlay"},
        ("recording", "preview_overlay_size"): {"pill", "small", "medium", "large"},
        ("hotkey", "mode"): {"toggle", "hold"},
        ("model", "backend"): {"auto", "faster-whisper", "whisper-torch", "whisper.cpp"},
        ("model", "device"): {"auto", "cuda", "cpu"},
        ("model", "compute"): {"auto", "float16", "int8"},
        ("insertion", "mode"): {"auto", "typed", "paste"},
        ("recording", "command"): {"auto", "pw-record", "parecord"},
    }
    _BOOLS = {("general", "copy_to_clipboard"), ("general", "tray_enabled"),
              ("recording", "preview_enabled"),
              ("processing", "remove_filler_words"), ("processing", "punctuation_enabled"),
              ("ai", "enabled"), ("sounds", "enabled"), ("notifications", "enabled"),
              ("history", "save"), ("history", "save_audio"), ("server", "enabled"),
              ("recording", "skip_silent")}

    def _coerce(self, section: str, key: str, value: Any) -> tuple[bool, Any]:
        if (section, key) in self._BOOLS:
            return (isinstance(value, bool), value)
        if (section, key) in self._ENUMS:
            return (isinstance(value, str) and value in self._ENUMS[(section, key)], value)
        if (section, key) == ("general", "language"):
            import re as _re
            ok = isinstance(value, str) and bool(
                _re.fullmatch(r"auto|[a-z]{2,3}(-[A-Za-z0-9]{2,8})?", value.strip()))
            return (ok, value.strip() if ok else value)
        rule = self._VALIDATORS.get((section, key))
        if rule:
            kind, bound = rule
            if kind == "str":
                ok = isinstance(value, str) and 0 < len(value) <= bound \
                    and not value.startswith("-")
                return (ok, value)
            try:
                num = float(value) if kind == "float" else int(value)
                if isinstance(value, bool) or not (bound[0] <= num <= bound[1]):
                    return (False, value)
                return (True, num)
            except (TypeError, ValueError):
                return (False, value)
        # unvalidated pass-through keys the UI owns (lists, dictionaries)
        if (section, key) in (("processing", "filler_words"),
                              ("processing", "dictionary"), ("hotkey", "modifiers")):
            if not isinstance(value, list):
                return (False, value)
            if key == "modifiers" and any(m not in ("ctrl", "alt", "shift", "super")
                                          for m in value):
                return (False, value)
            if key == "filler_words" and any(not isinstance(w, str) or len(w) > 64
                                             or not w.strip() for w in value):
                return (False, value)
            if key == "dictionary":
                for entry in value:
                    if (not isinstance(entry, dict)
                            or not isinstance(entry.get("triggers", []), list)
                            or not isinstance(entry.get("replacement", ""), str)
                            or len(entry.get("replacement", "")) > 512):
                        return (False, value)
            return (True, value)
        return (False, value)  # unknown key -> reject

    def api_config_post(self, body: dict) -> dict:
        """Whitelisted, validated merge; rejects unknown keys and bad types."""
        allowed = {
            "general": {"language", "copy_to_clipboard"},
            "hotkey": {"key", "modifiers", "mode", "cancel_key"},
            "recording": {"command", "device", "max_seconds", "skip_silent",
                          "first_pcm_timeout", "preview_enabled", "preview_mode",
                          "preview_interval", "preview_min_audio"},
            "model": {"backend", "name", "device", "compute", "whispercpp_model"},
            "processing": {"remove_filler_words", "filler_words",
                           "punctuation_enabled", "punctuation_prefix", "dictionary"},
            "ai": {"enabled", "base_url", "model", "api_key_env",
                   "temperature", "timeout_seconds", "max_retries"},
            "insertion": {"mode", "type_delay_ms", "paste_threshold_chars"},
            "sounds": {"enabled", "volume"},
            "notifications": {"enabled"},
            "history": {"save", "save_audio", "audio_budget_gb"},
            "server": {"enabled", "port"},
        }
        # model.name / ai.max_retries validated separately (model aliasing / small int)
        changed: list[str] = []
        rejected: list[str] = []
        for section, keys in allowed.items():
            for key in keys:
                if section in body and key in body[section]:
                    value = body[section][key]
                    if (section, key) == ("model", "name"):
                        value = backends.ALIASES.get(str(value).strip().lower(),
                                                     str(value).strip().lower())
                        ok = value in backends.FW_MODEL_REPOS or value == "auto"
                    elif (section, key) == ("ai", "max_retries"):
                        try:
                            ok = isinstance(value, (int, float)) and not isinstance(value, bool) \
                                and 0 <= int(value) <= 10
                            value = int(value)
                        except (TypeError, ValueError):
                            ok = False
                    else:
                        ok, value = self._coerce(section, key, value)
                    if not ok:
                        rejected.append(f"{section}.{key}")
                        continue
                    if self.cfg.get(section, {}).get(key) != value:
                        changed.append(f"{section}.{key}")
                    self.cfg.setdefault(section, {})[key] = value
        save_config(self.cfg)
        return {"ok": not rejected, "changed": changed, "rejected": rejected,
                "note": "some changes apply after the daemon restarts"}


class _Handler(BaseHTTPRequestHandler):
    webui_ref: WebUI | None = None
    MAX_BODY = 64 * 1024

    def log_message(self, *args) -> None:  # quiet
        pass

    # -- request guards (CSRF / DNS-rebinding / abuse) --------------------------

    def _host_ok(self) -> bool:
        """Only our own origin may talk to us: blocks DNS rebinding (reading
        GETs from a rebound domain) and cross-site form posts."""
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.webui_ref.port if self.webui_ref else ""
        allowed = {"127.0.0.1", "localhost",
                   f"127.0.0.1:{port}", f"localhost:{port}",
                   f"[::1]:{port}", "::1"}
        return host in allowed

    def _origin_ok(self) -> bool:
        """Same-origin browser requests carry Origin == our own URL; curl
        carries none. Anything else (a website's fetch/form) is rejected."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")

    def _forbidden(self, why: str) -> None:
        self._json({"error": why}, code=403)

    # -- plumbing --------------------------------------------------------------

    def _json(self, obj: Any, code: int = 200) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        if length > self.MAX_BODY:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode())
        except json.JSONDecodeError:
            return {}

    # -- routes ------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        w = self.webui_ref
        assert w is not None
        if not self._host_ok():
            return self._forbidden("bad host")
        if self.path in ("/", "/index.html"):
            data = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path in ("/history", "/history.html"):
            data = HISTORY_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/status":
            self._json(w.api_status())
        elif self.path == "/api/models":
            self._json(w.api_models())
        elif self.path == "/api/config":
            self._json(w.api_config_get())
        elif self.path.startswith("/api/history"):
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(self.path)
            if parsed.path == "/api/history/audio":
                return self._serve_history_audio(parsed)
            qs = parse_qs(parsed.query)
            self._json(w.api_history(qs.get("q", [""])[0],
                                     int(qs.get("limit", ["100"])[0])))
        else:
            self._json({"error": "not found"}, 404)

    def _serve_history_audio(self, parsed) -> None:
        """Stream a retained WAV - only for files recorded by the app."""
        from urllib.parse import parse_qs
        w = self.webui_ref
        qs = parse_qs(parsed.query)
        try:
            ts = float(qs.get("ts", ["0"])[0])
        except ValueError:
            return self._json({"error": "bad ts"}, 400)
        p = history_mod.audio_path_for(ts)
        if p is None or w is None:
            return self._json({"error": "no audio"}, 404)
        try:
            audio_dir = paths.audio_dir().resolve()
            if p.resolve().parent != audio_dir:
                return self._json({"error": "forbidden"}, 403)
            data = p.read_bytes()
        except OSError:
            return self._json({"error": "gone"}, 404)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        w = self.webui_ref
        assert w is not None
        if not self._host_ok() or not self._origin_ok():
            return self._forbidden("cross-site requests are not allowed")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return self._forbidden("application/json required")
        if (int(self.headers.get("Content-Length") or 0)) > self.MAX_BODY:
            return self._json({"error": "body too large"}, code=413)
        body = self._body()
        if self.path == "/api/config":
            self._json(w.api_config_post(body))
        elif self.path == "/api/models/select":
            self._json(w.api_select_model(body.get("name", "")))
        elif self.path == "/api/test-ai":
            self._json(w.api_test_ai(body))
        elif self.path == "/api/history/delete":
            self._json(w.api_history_delete(body))
        elif self.path == "/api/history/clear":
            self._json(w.api_history_clear())
        elif self.path == "/api/toggle":
            if w.daemon is not None:
                self._json(w.daemon.handle_request({"action": "toggle"}))
            else:
                self._json({"ok": False, "error": "daemon not attached"})
        else:
            self._json({"error": "not found"}, 404)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>FluidVoice Linux</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1420;--card:#171e2e;--line:#253048;--text:#e6ebf5;--mut:#8b96ad;
--acc:#3ac8c6;--ok:#4cc38a;--warn:#f2a33c;--err:#e5534b}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,sans-serif;
background:var(--bg);color:var(--text)}
.wrap{max-width:880px;margin:0 auto;padding:24px 20px 60px}
.nav{display:flex;gap:14px;margin-bottom:14px;font-size:13px}
.nav a{color:var(--mut);text-decoration:none;padding:6px 12px;border-radius:7px}
.nav a.on{color:var(--text);background:var(--card);border:1px solid var(--line)}
h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 10px;color:var(--mut);
text-transform:uppercase;letter-spacing:.06em}
.sub{color:var(--mut);margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:10px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.spread{justify-content:space-between}
.dot{width:9px;height:9px;border-radius:50%;background:var(--mut);display:inline-block}
.dot.rec{background:var(--err);animation:pulse 1s infinite}
.dot.busy{background:var(--warn);animation:pulse 1s infinite}
.dot.idle{background:var(--ok)}
@keyframes pulse{50%{opacity:.35}}
.models{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}
.model{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.model.active{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc)}
.model b{display:block;font-size:15px}.model .meta{color:var(--mut);font-size:12px;margin:2px 0 8px}
.model .note{color:var(--mut);font-size:12px;font-style:italic}
label{display:block;margin:10px 0 4px;color:var(--mut);font-size:13px}
input,select{width:100%;background:#0c111c;border:1px solid var(--line);color:var(--text);
border-radius:7px;padding:7px 10px;font:inherit}
input[type=checkbox]{width:auto}
button{background:var(--acc);border:0;color:#04211f;font-weight:600;border-radius:7px;
padding:7px 14px;font:inherit;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}
button:disabled{opacity:.5;cursor:default}
.hint{font-size:12px;color:var(--mut)}.err{color:var(--err)}.ok{color:var(--ok)}
.hist{border-left:2px solid var(--line);padding:2px 0 2px 12px;margin:6px 0}
.hist .t{color:var(--mut);font-size:12px}
.toast{position:fixed;bottom:18px;right:18px;background:var(--card);border:1px solid var(--acc);
border-radius:8px;padding:10px 16px;display:none}
.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.two{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="nav"><a href="/" class="on">Settings</a><a href="/history">History</a></div>
<h1>FluidVoice <span style="color:var(--mut);font-weight:400">Linux</span></h1>
<div class="sub"><span class="dot idle" id="dot"></span> <span id="state">idle</span>
&middot; <span id="backend"></span> &middot; <span id="cuda"></span>
&middot; model <b id="activeModel"></b></div>

<h2>Speech models</h2>
<div class="models" id="models"></div>
<div class="hint" id="warmupMsg" style="margin-top:8px"></div>

<h2>AI polish <span class="hint">(optional - any OpenAI-compatible endpoint)</span></h2>
<div class="card">
 <div class="row"><label style="margin:0 8px 0 0"><input type="checkbox" id="aiEnabled"> enabled</label>
  <span class="grow"></span><button class="ghost" id="testAi">Test connection</button>
  <span id="testAiOut" class="hint"></span></div>
 <div class="two">
  <div><label>Base URL</label><input id="aiUrl" placeholder="http://localhost:11434/v1"></div>
  <div><label>Model</label><input id="aiModel" placeholder="qwen3:8b"></div>
 </div>
 <div class="two">
  <div><label>API key env var</label><input id="aiKeyEnv" placeholder="FLUIDVOICE_API_KEY"></div>
  <div><label>Temperature</label><input id="aiTemp" type="number" step="0.1" min="0" max="2"></div>
 </div>
</div>

<h2>Dictation</h2>
<div class="card">
 <div class="two">
  <div><label>Hotkey (keysym)</label><input id="hkKey" placeholder="Right_Control"></div>
  <div><label>Mode</label><select id="hkMode"><option>toggle</option><option>hold</option></select></div>
 </div>
 <div class="two">
  <div><label>Language</label><input id="lang" placeholder="auto"></div>
  <div><label>Insertion</label><select id="insMode"><option>auto</option><option>typed</option><option>paste</option></select></div>
 </div>
 <div class="row" style="margin-top:10px">
  <label style="margin:0 8px 0 0"><input type="checkbox" id="fillers"> remove filler words</label>
  <label style="margin:0 8px 0 0"><input type="checkbox" id="punct"> spoken punctuation</label>
  <label style="margin:0 8px 0 0"><input type="checkbox" id="clip"> copy to clipboard</label>
  <label style="margin:0"><input type="checkbox" id="sounds"> sounds</label>
 </div>
 <div><label>Spoken-command prefix</label><input id="punctPrefix" placeholder="literal"></div>
</div>

<div class="row spread" style="margin-top:16px">
 <span class="hint" id="saveMsg"></span>
 <button id="save">Save settings</button>
</div>

<h2>History</h2>
<div id="history" class="hint">no transcriptions yet</div>
<div class="toast" id="toast"></div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=(p,opts)=>fetch(p,opts).then(r=>r.json());
const toast=m=>{const t=$('toast');t.textContent=m;t.style.display='block';
 setTimeout(()=>t.style.display='none',2500)};

async function refresh(){
 const s=await api('/api/status');
 const dot=$('dot');dot.className='dot '+(s.recording?'rec':s.busy?'busy':'idle');
 $('state').textContent=s.recording?'recording':s.busy?'processing':'idle';
 $('backend').textContent='backend: '+(s.backend||'-');
 $('cuda').textContent='GPU: '+(s.cuda?'yes':'no');
 $('activeModel').textContent=s.active_model;
 if(s.warmup.running){$('warmupMsg').textContent=
   'downloading/loading '+s.warmup.model+' ... (see daemon log)';}
 else if(s.warmup.error){$('warmupMsg').innerHTML=
   '<span class="err">warmup failed: '+esc(s.warmup.error)+'</span>';}
 const ms=await api('/api/models');
 $('models').innerHTML=ms.map(m=>`
  <div class="model ${m.active?'active':''}">
   <b>${m.name}${m.active?' ✓':''}</b>
   <div class="meta">${m.size} · ${m.langs} languages · ${m.downloaded?'downloaded':'not downloaded'}</div>
   <div class="note">${m.note}</div>
   ${m.active?'':`<button style="margin-top:8px" onclick="pick('${m.name}')">${m.downloaded?'Use':'Download & use'}</button>`}
  </div>`).join('');
}
async function pick(name){
 await api('/api/models/select',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({name})});
 toast('switching to '+name);refresh();
}
async function load(){
 const c=await api('/api/config');
 $('aiEnabled').checked=c.ai.enabled;$('aiUrl').value=c.ai.base_url;
 $('aiModel').value=c.ai.model||'';$('aiKeyEnv').value=c.ai.api_key_env;
 $('aiTemp').value=c.ai.temperature;$('hkKey').value=c.hotkey.key;
 $('hkMode').value=c.hotkey.mode;$('lang').value=c.general.language;
 $('insMode').value=c.insertion.mode;$('fillers').checked=c.processing.remove_filler_words;
 $('punct').checked=c.processing.punctuation_enabled;$('punctPrefix').value=c.processing.punctuation_prefix;
 $('sounds').checked=c.sounds.enabled;$('clip').checked=!!c.general.copy_to_clipboard;
 const h=await api('/api/history');
 $('history').innerHTML=h.length?h.map(e=>
  `<div class="hist"><div class="t">${new Date((e.ts||0)*1000).toLocaleString()}${e.ai?' · AI':''}${e.app?' · '+esc(e.app):''}</div><div>${esc(e.text||'')}</div></div>`).join('')
  :'no transcriptions yet';
}
$('save').onclick=async()=>{
 const body={general:{language:$('lang').value.trim()||'auto',copy_to_clipboard:$('clip').checked},
  hotkey:{key:$('hkKey').value.trim()||'Right_Control',mode:$('hkMode').value},
  ai:{enabled:$('aiEnabled').checked,base_url:$('aiUrl').value.trim(),
      model:$('aiModel').value.trim(),api_key_env:$('aiKeyEnv').value.trim(),
      temperature:parseFloat($('aiTemp').value)||0.2},
  insertion:{mode:$('insMode').value},
  processing:{remove_filler_words:$('fillers').checked,punctuation_enabled:$('punct').checked,
   punctuation_prefix:$('punctPrefix').value.trim()||'literal'},
  sounds:{enabled:$('sounds').checked}};
 const r=await api('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body)});
 $('saveMsg').textContent=r.changed.length?('saved: '+r.changed.join(', ')+' — '):'no changes — ';
 $('saveMsg').textContent+=r.note;toast('settings saved');
};
$('testAi').onclick=async()=>{
 $('testAiOut').textContent='testing...';$('testAiOut').className='hint';
 const r=await api('/api/test-ai',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({base_url:$('aiUrl').value.trim(),model:$('aiModel').value.trim()})});
 $('testAiOut').textContent=r.ok?('reply: '+r.reply):r.error;
 $('testAiOut').className=r.ok?'ok':'err';
};
load();refresh();setInterval(refresh,3000);
</script></body></html>
"""


HISTORY_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>FluidVoice History</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1420;--card:#171e2e;--line:#253048;--text:#e6ebf5;--mut:#8b96ad;
--acc:#3ac8c6;--ok:#4cc38a;--err:#e5534b}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,sans-serif;
background:var(--bg);color:var(--text)}
.wrap{max-width:880px;margin:0 auto;padding:24px 20px 60px}
.nav{display:flex;gap:14px;margin-bottom:14px;font-size:13px}
.nav a{color:var(--mut);text-decoration:none;padding:6px 12px;border-radius:7px}
.nav a.on{color:var(--text);background:var(--card);border:1px solid var(--line)}
h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mut);margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:10px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.spread{justify-content:space-between}
input{background:#0c111c;border:1px solid var(--line);color:var(--text);
border-radius:7px;padding:7px 10px;font:inherit;width:100%}
button{background:var(--acc);border:0;color:#04211f;font-weight:600;border-radius:7px;
padding:6px 12px;font:inherit;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--text)}
button.danger{background:transparent;border:1px solid var(--err);color:var(--err)}
button.sm{padding:4px 10px;font-size:12px}
.hint{font-size:12px;color:var(--mut)}
.e{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin-bottom:8px}
.e .meta{color:var(--mut);font-size:12px;display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.e .text{white-space:pre-wrap}
.e audio{width:100%;margin-top:8px}
mark{background:#3ac8c633;color:var(--acc);border-radius:3px;padding:0 2px}
</style></head><body><div class="wrap">
<div class="nav"><a href="/">Settings</a><a href="/history" class="on">History</a></div>
<h1>History</h1>
<div class="sub">Everything dictated with this app - search it, replay it, copy it.
This is the Linux counterpart of the macOS main window's transcript list.</div>
<div class="row" style="margin-bottom:12px">
  <input id="q" placeholder="Search transcripts, raw text, apps…" style="flex:1">
  <button onclick="load(0)">Search</button>
  <button class="ghost" onclick="load(0);document.getElementById('q').value=''">Reset</button>
  <button class="danger" onclick="clearAll()">Clear all</button>
</div>
<div id="list" class="hint">loading…</div>
<div class="hint" id="count" style="margin-top:10px"></div>
</div>
<script>
let t=null,entries=[];
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=ts=>new Date(ts*1000).toLocaleString();
function hl(text){
  const q=document.getElementById('q').value.trim();
  const s=esc(text);
  if(!q)return s;
  try{return s.replace(new RegExp('('+q.replace(/[.*+?^\${}()|[\\]\\\\]/g,'\\\\$&')+')','gi'),'<mark>$1</mark>');}
  catch(e){return s;}
}
async function load(){
  const q=document.getElementById('q').value;
  const r=await fetch('/api/history?limit=200&q='+encodeURIComponent(q)).then(r=>r.json());
  entries=Array.isArray(r)?r:[];
  render();
}
function render(){
  const el=document.getElementById('list');
  if(!entries.length){el.innerHTML='<div class="card hint">No dictations yet. Press your hotkey and speak - transcripts land here.</div>';}
  else el.innerHTML=entries.map(e=>`
    <div class="e">
      <div class="meta"><span>${esc(fmt(e.ts))}</span>
        <span>${e.duration_s?s.toFixed?'':''}${Number(e.duration_s||0).toFixed(1)}s</span>
        ${e.app?`<span>${esc(e.app)}</span>`:''}
        ${e.mode?`<span>${esc(e.mode)}</span>`:''}
        ${e.ai?'<span style="color:var(--acc)">AI polished</span>':''}
        <span style="flex:1"></span>
        <button class="sm ghost" onclick="copyTs(${e.ts})">Copy</button>
        <button class="sm danger" onclick="del(${e.ts})">Delete</button></div>
      <div class="text">${hl(e.text||e.raw||'')}</div>
      ${e.audio?`<audio controls preload="none" src="/api/history/audio?ts=${e.ts}"></audio>`:''}
    </div>`).join('');
  document.getElementById('count').textContent=entries.length+' entries'+(entries.length>=200?' (showing latest 200)':'');
}
function find(ts){return entries.find(e=>Math.abs(e.ts-ts)<1e-6);}
async function copyTs(ts){
  const e=find(ts);if(!e)return;
  await navigator.clipboard.writeText(e.text||e.raw||'');
}
async function del(ts){
  if(!confirm('Delete this entry?'))return;
  await fetch('/api/history/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ts})});
  load();
}
async function clearAll(){
  if(!confirm('Delete ALL history and retained audio?'))return;
  await fetch('/api/history/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  load();
}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')load();});
load();
</script></body></html>
"""
