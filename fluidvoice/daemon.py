"""The FluidVoiceLinux daemon: hotkey -> record -> transcribe -> polish -> type.

Structure:
  Daemon            state machine (idle/recording/busy), hotkey + socket wiring
  DictationPipeline one utterance: wav -> transcribe -> post-process -> optional
                    AI polish -> insert -> history. Every step is injectable so
                    the whole flow is unit-testable without audio, X11 or GPU.
"""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import __version__, backends, control, insertion, ui
from . import history as history_mod
from . import paths
from .ai.client import AIClient, AIError
from .ai.prompts import default_dictation_prompt
from .audio_utils import duration_seconds, is_silent
from .config import load_config
from .media import MediaController
from .processing import post_process
from .processing.per_app import match_app_prompt, system_prompt_for
from .recorder import Recorder, RecorderError


def log(msg: str) -> None:
    print(f"[fluidvoice] {time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


Inserter = Callable[[str, dict], str]
BackendFactory = Callable[[dict], Any]


class DictationPipeline:
    """Processes one finished recording into typed text (fully injectable)."""

    def __init__(self, cfg: dict, backend: Any, *,
                 inserter: Inserter = insertion.insert_text,
                 polisher: Callable[[str], str] | None = None,
                 history_writer: Callable[[dict, Path | None], None] | None = None,
                 key_presser: Callable[[str], None] | None = None,
                 rewriter: Callable[[str, str | None], str] | None = None,
                 logger: Callable[[str], None] = log):
        self.cfg = cfg
        self.backend = backend
        self.inserter = inserter
        self.polisher = polisher  # None -> build AIClient lazily when enabled
        self.history_writer = history_writer  # None -> history_mod.append
        self.key_presser = key_presser or self._press_send_key
        self.rewriter = rewriter
        self.log = logger
        self._pending_send_key: str | None = None
        self.notify = lambda title, body="": ui.notify(title, body, enabled=cfg["notifications"]["enabled"])

    # -- steps ------------------------------------------------------------

    def _should_skip(self, wav: Path, duration: float) -> bool:
        if not self.cfg["recording"].get("skip_silent"):
            return False
        return duration <= 4.0 and is_silent(str(wav))

    def _transcribe(self, wav: Path) -> dict:
        return self.backend.transcribe(wav, language=self.cfg["general"]["language"])

    def _polish(self, text: str, app_hint: str | None = None) -> tuple[str, bool]:
        """Returns (text, ai_used) - falls back to the raw text on AI errors.
        Per-app prompt rules (upstream per-app prompt sets) extend the
        dictation prompt when the target app matches."""
        if not self.cfg["ai"].get("enabled"):
            return text, False
        polisher = self.polisher or AIClient(self.cfg).polish
        instructions = match_app_prompt(
            self.cfg["ai"].get("per_app_prompts", []), app_hint)
        try:
            if instructions and self.polisher is None:
                prompt = system_prompt_for(default_dictation_prompt(),
                                           instructions)
                return polisher(text, system_prompt=prompt), True
            return polisher(text), True
        except AIError as e:
            self.log(f"AI polish failed ({e}); using raw transcription")
            return text, False

    def _rewrite(self, instruction: str, context: str | None, raw: str,
                 duration: float, wav: Path) -> dict | None:
        from . import rewrite as rewrite_mod
        try:
            rewriter = self.rewriter or rewrite_mod.run_rewrite
            rewritten = rewriter(instruction, context)
        except rewrite_mod.RewriteError as e:
            self.log(f"rewrite failed: {e}")
            self.notify("FluidVoice", f"Rewrite failed: {e}")
            return None
        strategy = self._insert(rewritten)
        out = {"raw": raw, "text": rewritten, "ai": True,
               "strategy": strategy, "mode": "rewrite"}
        self.log(f"rewrote ({strategy}, {len(rewritten)} chars): {rewritten[:120]}")
        self._write_history(
            {"ts": time.time(), "duration_s": round(duration, 2), "raw": raw,
             "text": rewritten, "ai": True, "backend": self.backend.name,
             "app": None, "mode": "rewrite"}, wav)
        return out

    def _command(self, instruction: str, raw: str,
                 duration: float, wav: Path) -> dict:
        """Command mode turn 0: hand the instruction back to the daemon (the
        CommandSession inserts nothing, polishes nothing and writes history
        only for EXECUTED commands, later)."""
        self.log(f"command instruction ({len(instruction)} chars): {instruction[:120]}")
        return {"mode": "command", "text": instruction, "raw": raw,
                "duration_s": round(duration, 2)}

    def _after_ai_formatting(self, text: str) -> str:
        """GAAV + spoken-send stripping (upstream post-AI steps)."""
        from .processing.extra_formats import apply_gaav, parse_spoken_send
        p = self.cfg.get("processing", {})
        if p.get("gaav_enabled"):
            text = apply_gaav(text,
                             lowercase_first=p.get("gaav_lowercase_first", True),
                             remove_trailing_period=p.get("gaav_remove_trailing_period", True))
        if self.cfg["recording"].get("spoken_send_enabled"):
            result = parse_spoken_send(text,
                                       self.cfg["recording"].get("spoken_send_phrase", "send it"))
            self._pending_send_key = (self.cfg["recording"].get("spoken_send_key", "enter")
                                      if result.should_send else None)
            return result.text
        return text

    def _press_send_key(self, spec: str) -> None:
        try:
            insertion.press_key(spec)
        except insertion.InsertError as e:
            self.log(f"send-key failed: {e}")

    def _insert(self, text: str) -> str:
        try:
            strategy = self.inserter(text, self.cfg)
        except insertion.InsertError as e:
            self.log(f"insertion failed: {e}")
            self.notify("FluidVoice", f"Could not type text: {e}\n(copied to clipboard instead)")
            insertion.clipboard_fallback(text)
            strategy = "clipboard-fallback"
        if self.cfg.get("general", {}).get("copy_to_clipboard"):
            insertion.copy_to_clipboard(text)  # upstream copyTranscriptionToClipboard
        return strategy

    def _write_history(self, entry: dict, wav: Path) -> None:
        if not self.cfg["history"].get("save"):
            return
        hcfg = self.cfg["history"]
        if self.history_writer is not None:
            self.history_writer(entry, wav if hcfg.get("save_audio") else None)
        else:
            history_mod.append(entry,
                               audio_src=wav if hcfg.get("save_audio") else None,
                               keep_audio=hcfg.get("save_audio", False),
                               budget_gb=hcfg.get("audio_budget_gb", 4.0))

    # -- orchestration ------------------------------------------------------

    def run(self, wav: Path, app_hint: str | None,
            mode: str = "dictate", rewrite_context: str | None = None) -> dict | None:
        """Returns the result dict (raw/text/ai/strategy) or None if nothing was typed."""
        from .audio_utils import pad_wav
        started = time.monotonic()
        try:
            duration = duration_seconds(str(wav))
            if self._should_skip(wav, duration):
                self.log("silent recording skipped")
                return None
            pad_wav(wav)  # whisper.cpp requires >= 1s (16000 samples) of audio
            try:
                result = self._transcribe(wav)
            except Exception as e:
                self.log(f"transcription failed: {e}")
                self.notify("FluidVoice", f"Transcription failed: {e}")
                return None
            raw = result.get("text", "")
            if not raw.strip():
                self.log("empty transcription")
                return None
            text = post_process(raw, self.cfg, app_hint=app_hint)
            if mode == "rewrite":
                return self._rewrite(text, rewrite_context, raw, duration, wav)
            if mode == "command":
                return self._command(text, raw, duration, wav)
            polished, ai_used = self._polish(text, app_hint=app_hint)
            polished = self._after_ai_formatting(polished)
            strategy = self._insert(polished)
            if self._pending_send_key:
                spec, self._pending_send_key = self._pending_send_key, None
                self.key_presser(spec)
                strategy += f"+{spec}"
            out = {"raw": raw, "text": polished, "ai": ai_used, "strategy": strategy}
            self.log(f"typed ({strategy}, {len(polished)} chars, {duration:.1f}s audio, "
                     f"{time.monotonic() - started:.1f}s total): {polished[:120]}")
            self._write_history(
                {"ts": time.time(), "duration_s": round(duration, 2), "raw": raw,
                 "text": polished, "ai": ai_used, "backend": self.backend.name,
                 "app": app_hint}, wav)
            return out
        finally:
            wav.unlink(missing_ok=True)


class Daemon:
    def __init__(self, cfg: dict | None = None, *,
                 recorder: Recorder | None = None,
                 backend_factory: BackendFactory = backends.load_backend,
                 pipeline_factory=DictationPipeline,
                 command_session_factory=None,
                 use_hotkey: bool = True, use_sounds: bool = True):
        self.cfg = cfg or load_config()
        self.use_hotkey = use_hotkey
        self.use_sounds = use_sounds
        self.recorder = recorder or Recorder(
            command=self.cfg["recording"]["command"],
            device=self.cfg["recording"].get("device", ""),
            sample_rate=self.cfg["recording"].get("sample_rate", 16000))
        self._backend_factory = backend_factory
        self._pipeline_factory = pipeline_factory
        self._command_session_factory = command_session_factory
        self.backend: Any = None  # lazy: loads model on first use
        self.recording = False
        self.busy = False  # transcription/insertion in flight
        self.last_result: dict = {}
        self._app_hint: str | None = None
        self._rewrite_context: str | None = None
        self._rewrite_mode = False
        # Command mode: recording flag + the awaiting-confirmation state
        self._command_mode = False
        self._command_session = None
        self._command_pending = False
        self._command_display = None
        self._command_timer: threading.Timer | None = None
        self._command_hotkey = None
        self._watchdog: threading.Timer | None = None
        self._preview: Any = None
        self._closing_display: Any = None
        self._tray: Any = None
        self._media = MediaController(log=log)
        self.warmup: dict = {"running": False, "error": None, "model": None}
        self._warmup_lock = threading.Lock()
        self._lock = threading.Lock()
        self._hotkey = None
        self._rewrite_hotkey = None
        self._srv: Any = None
        self._process_thread: threading.Thread | None = None

    # -- lifecycle -----------------------------------------------------------

    def run(self) -> None:
        log(f"FluidVoiceLinux v{__version__} starting")
        self._sweep_stale_tmp()
        try:
            self.backend = self._backend_factory(self.cfg)
        except Exception as e:
            log(f"WARN speech backend not ready yet ({e}); will retry on first use")
            self.backend = None
        else:
            if not self.cfg["model"].get("eager_warmup", True):
                pass  # warmup disabled (e.g. test isolation on small GPUs)
            else:
                # Load the model in the background so the live preview works
                # from the very first dictation (lazy otherwise).
                backend_ref = self.backend

                def _warm():
                    try:
                        backend_ref.warmup()
                        log("speech model loaded (preview ready)")
                    except Exception as e:
                        log(f"WARN model warmup failed: {e}")

                threading.Thread(target=_warm, name="fluidvoice-warmup",
                                 daemon=True).start()

        if self.use_hotkey:
            self._start_hotkey()

        self._start_tray()
        self._maybe_first_run_onboard()

        ready = threading.Event()
        self._srv = control.serve(self.handle_request, ready=ready)
        ready.wait(timeout=5)
        log(f"control socket: {paths.socket_path()}")

        import os as _os
        cfg_shown = _os.environ.get("FLUIDVOICE_CONFIG") or paths.config_file()
        log("ready - press the hotkey to dictate "
            f"(or run `fluidvoice toggle`; config: {cfg_shown})")

        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            while not stop.is_set():
                time.sleep(0.3)
        finally:
            self.shutdown()

    def _start_tray(self) -> None:
        """Panel/tray icon (StatusNotifierItem): click toggles dictation,
        right-click opens the dropdown menu, tooltip shows state + hotkey."""
        if not self.cfg["general"].get("tray_enabled", True):
            return
        try:
            from .tray import TrayIcon
            tray = TrayIcon(on_activate=self.toggle,
                            on_secondary=self._open_settings,
                            tooltip=self._tray_tooltip,
                            build_menu=self._build_tray_menu,
                            log=log)
            if tray.start():
                self._tray = tray
                log("tray icon active (click = dictate, right-click = menu)")
            else:
                log("tray unavailable on this desktop - running headless")
        except Exception as e:
            log(f"WARN tray unavailable: {e}")

    def _build_tray_menu(self) -> list:
        """Native dropdown model, mirroring the macOS menu bar menu:
        status, cancel, copy last transcript, settings, microphone, quit."""
        with self._lock:
            recording, busy = self.recording, self.busy
        hk = self.cfg["hotkey"].get("key", "")
        state = ("Recording…" if recording else
                 "Processing…" if busy else "Ready to Record")
        status = f"{state} ({hk})" if hk else state
        text = (self.last_result or {}).get("text") or ""
        if not text:
            try:
                entries = history_mod.tail(1)
                text = entries[0].get("text", "") if entries else ""
            except Exception:
                text = ""
        device = self.cfg["recording"].get("device", "")
        mics = [{"kind": "check", "label": "Auto (system default)",
                 "checked": not device,
                 "action": lambda: self._set_device("")}]
        from .tray import list_microphones
        for m in list_microphones():
            mics.append({"kind": "check", "label": m["description"],
                         "checked": device == m["name"],
                         "action": lambda n=m["name"]: self._set_device(n)})
        return [
            {"kind": "item", "label": status, "enabled": False},
            {"kind": "item", "label": "Cancel Dictation (Esc)",
             "enabled": recording, "action": self.cancel},
            {"kind": "item", "label": "Copy Last Transcript",
             "enabled": bool(text), "action": self._copy_last_transcript},
            {"kind": "separator"},
            {"kind": "item", "label": "Settings…",
             "action": lambda: self._open_settings()},
            {"kind": "item", "label": "History",
             "action": lambda: self._open_settings("/history")},
            {"kind": "item", "label": "Microphone", "children": mics},
            {"kind": "separator"},
            {"kind": "item", "label": "Quit Fluid Voice",
             "action": self._quit_gracefully},
        ]

    def _copy_last_transcript(self) -> None:
        text = (self.last_result or {}).get("text") or ""
        if not text:
            from . import history as history_mod
            entries = history_mod.tail(1)
            text = entries[0].get("text", "") if entries else ""
        if not text:
            ui.notify("FluidVoice", "Nothing to copy",
                      enabled=self.cfg["notifications"]["enabled"])
            return
        import shutil
        import subprocess
        tool = next((t for t in ("xclip", "xsel", "wl-copy")
                     if shutil.which(t)), None)
        if not tool:
            ui.notify("FluidVoice", "No clipboard tool found (install xclip)",
                      enabled=self.cfg["notifications"]["enabled"])
            return
        args = ([tool, "-selection", "clipboard"] if tool == "xclip"
                else [tool, "-clipboard", "-in"] if tool == "xsel"
                else [tool])
        try:
            subprocess.run(args, input=text.encode(), check=True, timeout=3,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            log(f"copied last transcript ({len(text)} chars)")
        except Exception as e:
            log(f"copy failed: {e}")

    def _set_device(self, device: str) -> None:
        with self._lock:
            if self.recording or self.busy:
                log("cannot switch microphone while dictating")
                return
            self.cfg["recording"]["device"] = device
            try:
                from .config import save_config
                save_config(self.cfg)
            except Exception as e:
                log(f"WARN could not save microphone choice: {e}")
            self._rebuild_recorder()
            log(f"microphone set to {device or 'auto'}")

    def _quit_gracefully(self) -> None:
        log("quit requested from menu")
        import os
        threading.Timer(0.1, lambda: os.kill(os.getpid(),
                                             signal.SIGTERM)).start()

    def _tray_recording(self, recording: bool) -> None:
        if self._tray is not None:
            self._tray.set_recording(recording)
        if self._hotkey is not None:
            try:
                self._hotkey.set_recording(recording)  # Escape grab while up
            except Exception:
                pass

    def _tray_tooltip(self) -> str:
        with self._lock:
            if self.recording:
                state = "Recording… click to stop"
            elif self.busy:
                state = "Processing…"
            else:
                state = "Ready"
        hk = self.cfg["hotkey"].get("key", "")
        hint = f" — {hk} or click to dictate" if hk else ""
        return f"FluidVoice: {state}{hint}"

    def _spawn_app(self, *args: str) -> None:
        """Launch the native GTK app in the same interpreter/env as us."""
        import os
        import subprocess
        if os.environ.get("FLUIDVOICE_NO_APP_SPAWN"):  # tests/headless
            log(f"app launch suppressed ({' '.join(args) or 'app'})")
            return
        try:
            subprocess.Popen([sys.executable, "-m", "fluidvoice", "app", *args],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            log(f"WARN could not launch the app: {e}")

    def _open_settings(self, page: str = "") -> None:
        target = (page or "").strip("/") or "settings"
        self._spawn_app("--open", "history" if target == "history" else "settings")
        log(f"tray: opened {target}")

    def shutdown(self) -> None:
        log("shutting down")
        if self.recording:
            self.recorder.cancel()
            self.recording = False
        if self._watchdog:
            self._watchdog.cancel()
        self._stop_preview()
        self._close_closing_display()
        self.cancel_pending_command()  # pill + Escape grab gone before hotkeys
        if self._tray:
            self._tray.stop()
        if self._hotkey:
            self._hotkey.stop()
        if self._rewrite_hotkey:
            self._rewrite_hotkey.stop()
        if self._command_hotkey:
            self._command_hotkey.stop()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
            paths.socket_path().unlink(missing_ok=True)

    @staticmethod
    def _sweep_stale_tmp() -> None:
        """Delete fluidvoice temp wavs abandoned by hard crashes (older than 1 day)."""
        import glob
        import time as _time
        cutoff = _time.time() - 86400
        for f in glob.glob("/tmp/fluidvoice-*.wav"):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.unlink(f)
            except OSError:
                pass

    def _start_hotkey(self) -> str | None:
        """(Re-)grab the dictation hotkeys. Returns the first error, if any."""
        from .hotkey import HotkeyError, HotkeyListener
        error = None
        hk = self.cfg["hotkey"]
        try:
            self._hotkey = HotkeyListener(
                key=hk["key"], modifiers=hk.get("modifiers", []),
                mode=hk.get("mode", "toggle"),
                on_toggle=self.toggle,
                on_cancel=self.cancel,
                cancel_key=hk.get("cancel_key", "Escape"),
            )
            self._hotkey.start()
            for line in self._hotkey.summary:
                log(line)
        except HotkeyError as e:
            self._hotkey = None
            log(f"WARN hotkey unavailable: {e}")
            ui.notify("FluidVoice", f"Hotkey unavailable: {e}\n"
                      "Bind a DE shortcut to `fluidvoice toggle` instead.",
                      timeout_ms=8000, enabled=self.cfg["notifications"]["enabled"])
            error = str(e)
        rewrite_key = (hk.get("rewrite_key") or "").strip()
        if rewrite_key:
            try:
                self._rewrite_hotkey = HotkeyListener(
                    key=rewrite_key, modifiers=[], mode="toggle",
                    on_toggle=self.start_rewrite)
                self._rewrite_hotkey.start()
                for line in self._rewrite_hotkey.summary:
                    log(line)
            except HotkeyError as e:
                self._rewrite_hotkey = None
                log(f"WARN rewrite hotkey unavailable: {e}")
                error = error or str(e)
        command_key = (hk.get("command_key") or "").strip()
        if command_key:
            try:
                self._command_hotkey = HotkeyListener(
                    key=command_key, modifiers=[], mode="toggle",
                    on_toggle=self._on_command_hotkey,
                    on_cancel=self.cancel_pending_command,
                    cancel_key=hk.get("cancel_key", "Escape"))
                self._command_hotkey.start()
                for line in self._command_hotkey.summary:
                    log(line)
            except HotkeyError as e:
                self._command_hotkey = None
                log(f"WARN command hotkey unavailable: {e}")
                error = error or str(e)
        return error

    def _restart_hotkey(self) -> None:
        """Re-grab the hotkeys after a settings change (frees the old grabs
        first). Raises on failure so the settings UI can surface it."""
        if not self.use_hotkey:
            return
        for attr in ("_hotkey", "_rewrite_hotkey", "_command_hotkey"):
            listener = getattr(self, attr)
            if listener is not None:
                try:
                    listener.stop()
                except Exception as e:
                    log(f"WARN stopping old hotkey grab failed: {e}")
                setattr(self, attr, None)
        error = self._start_hotkey()
        if error:
            raise RuntimeError(f"hotkey re-bind failed: {error} "
                               "(fix the key and save again)")

    def _rebuild_recorder(self) -> None:
        """New Recorder from the current cfg (command/device changed)."""
        rcfg = self.cfg["recording"]
        self.recorder = Recorder(command=rcfg.get("command", "auto"),
                                 device=rcfg.get("device", ""),
                                 sample_rate=rcfg.get("sample_rate", 16000))

    def _apply_tray_setting(self) -> None:
        enabled = self.cfg["general"].get("tray_enabled", True)
        if not enabled and self._tray is not None:
            self._tray.stop()
            self._tray = None
            log("tray disabled (settings change)")
        elif enabled and self._tray is None:
            self._start_tray()

    def apply_config(self, changed: list[str]) -> dict:
        """Apply just-saved settings that need more than a cfg-dict update
        (everything else is read from cfg at use time, or needs a daemon
        restart - see config.RESTART_REQUIRED). Feedback for the settings UI."""
        applied: list[str] = []
        errors: list[str] = []

        def _try(area: str, fn) -> None:
            try:
                fn()
                applied.append(area)
            except Exception as e:  # noqa: BLE001 - surfaced in the UI
                errors.append(f"{area}: {e}")

        if any(k.startswith("hotkey.") for k in changed):
            _try("hotkeys", self._restart_hotkey)
        if "recording.command" in changed:
            _try("recorder", self._rebuild_recorder)
        if "recording.device" in changed:
            def _set_mic() -> None:
                with self._lock:
                    if self.recording or self.busy:
                        raise RuntimeError("cannot switch microphone while dictating")
                self._set_device(self.cfg["recording"].get("device", ""))
            _try("microphone", _set_mic)
        if "general.tray_enabled" in changed:
            _try("tray", self._apply_tray_setting)
        return {"applied": applied, "errors": errors}

    # -- model warmup / hot-swap (native-app spec: select-model over socket) ----

    def _active_model_name(self) -> str:
        name = str(self.cfg["model"].get("name", "auto"))
        if name in ("", "auto"):
            return backends.resolve_model_name(self.cfg["model"]["name"])
        return backends.ALIASES.get(name.lower(), name.lower())

    def select_model(self, name: str) -> dict:
        name = backends.ALIASES.get(name.strip().lower(), name.strip().lower())
        if name not in backends.FW_MODEL_REPOS:
            return {"ok": False, "error": f"unknown model '{name}'"}
        with self._warmup_lock:
            if self.warmup["running"]:
                return {"ok": False, "error": "a model download is already running"}
            self.warmup = {"running": True, "error": None, "model": name}
        threading.Thread(target=self._warmup_model, args=(name,),
                         daemon=True).start()
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
            from .config import save_config
            save_config(self.cfg)
            self.backend = backend  # hot-swap into the running daemon
            self.warmup = {"running": False, "error": None, "model": name}
            log(f"model switched to {name} (hot-swapped)")
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.cfg["model"]["name"] = previous  # rollback, keep usable
            self.warmup = {"running": False, "error": str(e)[:300], "model": name}
            log(f"model switch to {name} failed: {e}")

    def _reload_backend(self) -> None:
        """Rebuild the loaded backend after engine-option changes. Config
        stays saved even on failure - the running backend keeps its last
        working state until the next try."""
        model = self._active_model_name()
        try:
            backend = backends.load_backend(self.cfg)
            backend.warmup()
            self.backend = backend
            self.warmup = {"running": False, "error": None, "model": model}
        except Exception as e:  # noqa: BLE001 - surfaced in the UI
            self.warmup = {"running": False, "error": str(e)[:300], "model": model}

    # -- control protocol ----------------------------------------------------

    def handle_request(self, req: dict) -> dict:
        action = req.get("action")
        if action == "toggle":
            recording = self.toggle()
            return {"ok": True, "recording": recording}
        if action == "cancel":
            self.cancel()
            return {"ok": True, "recording": False, "cancelled": True}
        if action == "paste-last":
            ok, detail = self.paste_last()
            return {"ok": ok, "error": detail if not ok else None}
        if action == "status":
            return {"ok": True, "recording": self.recording, "busy": self.busy,
                    "backend": self.backend.name if self.backend else None,
                    "version": __version__,
                    "warmup": dict(self.warmup),
                    "active_model": self._active_model_name()}
        if action == "shutdown":
            self._quit_gracefully()
            return {"ok": True}
        if action == "set-device":
            device = str(req.get("device", ""))
            self._set_device(device)
            return {"ok": True, "device": device}
        if action == "test-dictation":
            return self.test_dictation(float(req.get("seconds", 3.0)))
        if action == "get-config":
            from .config import mask_secrets
            return {"ok": True, "config": mask_secrets(self.cfg)}
        if action == "set-config":
            return self._set_config(req.get("config") or {})
        if action == "select-model":
            return self.select_model(str(req.get("name", "")))
        if action == "mics":
            from .tray import list_microphones
            return {"ok": True, "mics": list_microphones()}
        return {"ok": False, "error": f"unknown action {action!r}"}

    def _set_config(self, body: dict) -> dict:
        """Validated settings merge over the socket (native-app spec):
        validate -> save -> hot-apply what the daemon can take live."""
        from .config import (RESTART_REQUIRED, ENGINE_KEYS, apply_settings,
                             save_config)
        changed, rejected = apply_settings(self.cfg, body)
        if changed:
            try:
                save_config(self.cfg)
            except Exception as e:
                return {"ok": False, "error": f"save failed: {e}",
                        "changed": [], "rejected": rejected}
        restart = [k for k in changed if k in RESTART_REQUIRED]
        live = [k for k in changed if k not in RESTART_REQUIRED]
        applied: list[str] = []
        errors: list[str] = []
        if live:
            feedback = self.apply_config(live)
            applied = feedback.get("applied", [])
            errors = feedback.get("errors", [])
        if any(k in ENGINE_KEYS for k in changed):
            with self._warmup_lock:
                if not self.warmup["running"]:
                    self.warmup = {"running": True, "error": None,
                                   "model": self._active_model_name()}
                    threading.Thread(target=self._reload_backend,
                                     daemon=True).start()
                    applied.append("speech engine (reloading)")
                else:
                    errors.append("speech engine: a load is already running - "
                                  "save again once it finishes")
        note = ("restart the daemon to apply: " + ", ".join(restart)) \
            if restart else ""
        return {"ok": not rejected, "changed": changed, "rejected": rejected,
                "restart_required": restart, "applied": applied,
                "errors": errors, "note": note}

    # -- dictation -----------------------------------------------------------

    def start_rewrite(self) -> None:
        """Rewrite hotkey: capture the selection, then record the instruction."""
        from . import rewrite as rewrite_mod
        with self._lock:
            if self.recording or self.busy:
                return
            try:
                context = rewrite_mod.capture_selection()
            except Exception as e:
                log(f"selection capture failed: {e}")
                context = ""
            self._rewrite_mode = True
            self._rewrite_context = context or None
            log(f"rewrite mode (context: {len(context or '')} chars)")
            self._start_recording_locked()

    def start_command(self) -> None:
        """Command hotkey: start recording the spoken instruction."""
        from . import command as command_mod
        with self._lock:
            if self.recording or self.busy or self._command_pending:
                return
        ready = command_mod.command_mode_ready(self.cfg)
        if ready:
            log(ready)
            ui.notify("FluidVoice", f"Command mode unavailable: {ready}",
                      enabled=self.cfg["notifications"]["enabled"])
            return
        with self._lock:
            self._command_mode = True
            log("command mode")
            self._start_recording_locked()

    def _on_command_hotkey(self) -> None:
        """Command hotkey router: a second press CONFIRMS a pending proposal
        (the only execution trigger); otherwise it starts a recording."""
        if self._command_pending:
            self._confirm_pending_command()
        else:
            self.start_command()  # guards make this a no-op mid-recording

    def toggle(self) -> bool:
        with self._lock:
            if self.recording:
                self._stop_recording_locked()
                return False
            if self.busy:
                log("still processing previous dictation; ignoring toggle")
                return False
            self._start_recording_locked()
            return self.recording

    def _start_recording_locked(self) -> None:
        self._app_hint = insertion.active_window_class()
        fd, tmp = tempfile.mkstemp(prefix="fluidvoice-", suffix=".wav")
        os.close(fd)
        try:
            self.recorder.start(Path(tmp))
        except RecorderError as e:
            log(f"recorder error: {e}")
            ui.notify("FluidVoice", f"Recording failed: {e}",
                      enabled=self.cfg["notifications"]["enabled"])
            Path(tmp).unlink(missing_ok=True)
            return
        self.recording = True
        self._tray_recording(True)
        if self.cfg["recording"].get("pause_media", True):
            self._media.pause_if_playing()  # upstream: only what's playing
        ui.play_sound("start", self.cfg["sounds"]["volume"],
                      self.use_sounds and self.cfg["sounds"]["enabled"])
        log(f"recording (app={self._app_hint or '?'})")
        max_s = float(self.cfg["recording"].get("max_seconds", 300))
        self._watchdog = threading.Timer(max_s, self._auto_stop)
        self._watchdog.daemon = True
        self._watchdog.start()
        # Upstream firstPCMTimeout (2s): a live-but-silent source (muted mic,
        # wrong device, Bluetooth glitch) should fail fast, not record air
        # until max_seconds.
        self._start_preview(getattr(self.recorder, "raw_path", None))
        pcm_timeout = float(self.cfg["recording"].get("first_pcm_timeout", 2.0))
        if pcm_timeout > 0:
            t = threading.Timer(pcm_timeout, self._check_first_pcm, args=(Path(tmp),))
            t.daemon = True
            t.start()

    def _start_preview(self, raw_path) -> None:
        """Live transcription preview while recording (best-effort)."""
        rcfg = self.cfg["recording"]
        if not rcfg.get("preview_enabled", True) or raw_path is None:
            return
        try:
            from .overlay import FluidOverlay
            from .preview import (NotifyPreview, PreviewEngine,
                                  faster_whisper_transcriber)
            backend = self.backend
            model = getattr(backend, "_model", None)
            if backend is None or model is None:
                return  # not a ready faster-whisper backend
            mode = rcfg.get("preview_mode", "auto")
            if mode in ("auto", "overlay"):
                # FluidOverlay itself falls back to notifications when the
                # display/pill stack is unavailable.
                display = FluidOverlay(
                    raw_path=Path(raw_path),
                    bottom_offset=int(rcfg.get("preview_bottom_offset", 64)),
                    size=rcfg.get("preview_overlay_size", "medium"))
                actual = "overlay" if display.using_overlay else "notify"
            else:
                display = NotifyPreview()
                actual = "notify"
            display.start()
            engine = PreviewEngine(
                Path(raw_path),
                faster_whisper_transcriber(model, self.cfg["general"]["language"]),
                display.show,
                interval=float(rcfg.get("preview_interval", 1.2)),
                min_audio=float(rcfg.get("preview_min_audio", 1.0)))
            engine.start()
            self._preview = (engine, display)
            log(f"preview started ({actual})")
        except Exception as e:
            log(f"WARN preview unavailable: {e}")

    def _stop_preview(self, finishing: bool = False) -> None:
        preview, self._preview = self._preview, None
        if preview is None:
            return
        engine, display = preview
        engine.stop()
        if finishing:
            # Keep the pill up in its processing state (flat bars + shimmer,
            # like the Mac) until the final text is inserted.
            display.set_state("processing")
            self._closing_display = display
        else:
            display.close()

    def _close_closing_display(self) -> None:
        display, self._closing_display = self._closing_display, None
        if display is not None:
            display.close()

    def _check_first_pcm(self, wav: Path) -> None:
        with self._lock:
            if not self.recording or self.recorder.path != wav:
                return
            # audio streams into the RAW file during recording (the WAV is
            # only written at stop); fall back to the wav for stub recorders
            probe = getattr(self.recorder, "raw_path", None) or wav
            try:
                got_pcm = probe is not None and probe.exists() \
                    and probe.stat().st_size > 2048
            except OSError:
                got_pcm = False
            if not got_pcm:
                if self._watchdog:
                    self._watchdog.cancel()
                    self._watchdog = None
                self.recorder.cancel()
                self.recording = False
                self._tray_recording(False)
                self._media.resume()
                msg = "microphone produced no audio (muted or wrong device?) - stopped"
                log(msg)
                ui.notify("FluidVoice", msg, enabled=self.cfg["notifications"]["enabled"])

    def _auto_stop(self) -> None:
        # Re-check under the lock: cancel()/shutdown() may have finished in
        # between the timer firing and now - never start anything new here.
        with self._lock:
            if not self.recording:
                return
            log("max duration reached, stopping")
            self._stop_recording_locked()

    def _stop_recording_locked(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        self._stop_preview(finishing=True)
        # Stop cue fires at capture stop (upstream behavior), before waiting
        # for the recorder process to flush and exit.
        ui.play_sound("stop", self.cfg["sounds"]["volume"],
                      self.use_sounds and self.cfg["sounds"]["enabled"])
        wav = self.recorder.stop()
        self.recording = False
        self._tray_recording(False)
        self._media.resume()
        if wav is None or not Path(wav).exists() or Path(wav).stat().st_size < 200:
            log("no audio captured")
            self._rewrite_mode = False
            self._command_mode = False
            self._close_closing_display()
            if wav:
                Path(wav).unlink(missing_ok=True)
            return
        mode = "rewrite" if self._rewrite_mode else \
            "command" if self._command_mode else "dictate"
        context = self._rewrite_context
        self._rewrite_mode = False
        self._command_mode = False
        self._rewrite_context = None
        self._process_thread = threading.Thread(
            target=self._process,
            args=(Path(wav), self._app_hint, mode, context), daemon=True)
        self._process_thread.start()

    def cancel(self) -> None:
        with self._lock:
            if not self.recording:
                return
            if self._watchdog:
                self._watchdog.cancel()
                self._watchdog = None
            self._stop_preview()
            self.recorder.cancel()
            self.recording = False
            self._tray_recording(False)
            self._media.resume()
            self._rewrite_mode = False
            self._command_mode = False
        log("cancelled")
        ui.notify("FluidVoice", "Cancelled", enabled=self.cfg["notifications"]["enabled"])

    def _maybe_first_run_onboard(self) -> None:
        """Open onboarding once on first launch (macOS parity: the app opens
        onboarding before the first dictation)."""
        try:
            marker = paths.data_dir() / ".onboarded"
            if marker.exists() or history_mod.tail(1):
                return
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("opened\n")  # once only, even if skipped
            self._spawn_app("--onboard")
            log("first run detected - opened the setup page")
        except Exception as e:
            log(f"WARN onboarding open failed: {e}")

    def test_dictation(self, seconds: float = 3.0) -> dict:
        """Onboarding tryout (upstream's real-dictation step): record a few
        seconds and transcribe them WITHOUT typing anywhere."""
        with self._lock:
            if self.recording:
                return {"ok": False, "error": "currently recording"}
            if self.busy:
                return {"ok": False, "error": "busy"}
            self.busy = True
        fd, tmp = tempfile.mkstemp(prefix="fluidvoice-onboard-", suffix=".wav")
        os.close(fd)
        try:
            try:
                self.recorder.start(Path(tmp))
            except RecorderError as e:
                return {"ok": False, "error": f"recorder error: {e}"}
            time.sleep(max(1.0, min(seconds, 8.0)))
            wav = self.recorder.stop()
            if wav is None or not Path(wav).exists() \
                    or Path(wav).stat().st_size < 200:
                return {"ok": False,
                        "error": "no audio captured (muted or wrong mic?)"}
            duration = duration_seconds(Path(wav))
            if is_silent(Path(wav)):
                return {"ok": False, "duration_s": duration,
                        "error": "audio was silent - is the mic muted?"}
            backend = self._ensure_backend()
            result = backend.transcribe(Path(wav),
                                        self.cfg["general"]["language"]) or {}
            return {"ok": True, "duration_s": round(duration, 1),
                    "text": result.get("text", "")}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            Path(tmp).unlink(missing_ok=True)
            with self._lock:
                self.busy = False

    def paste_last(self) -> tuple[bool, str | None]:
        """Re-type the most recent transcription (upstream paste-last hotkey)."""
        if self.busy or self.recording:
            return False, "busy"
        text = (self.last_result or {}).get("text") or ""
        if not text:
            from . import history as history_mod
            entries = history_mod.tail(1)
            text = entries[0].get("text", "") if entries else ""
        if not text:
            return False, "nothing to paste"
        try:
            insertion.insert_text(text, self.cfg)
            log(f"pasted last transcription ({len(text)} chars)")
            return True, None
        except insertion.InsertError as e:
            log(f"paste-last failed: {e}")
            return False, str(e)

    # -- pipeline ------------------------------------------------------------

    def _ensure_backend(self):
        if self.backend is None:
            self.backend = self._backend_factory(self.cfg)
            log(f"speech backend: {self.backend.name}")
        return self.backend

    def _process(self, wav: Path, app_hint: str | None,
                 mode: str = "dictate", rewrite_context: str | None = None) -> None:
        self.busy = True
        out: dict = {}
        try:
            try:
                backend = self._ensure_backend()
            except Exception as e:
                log(f"transcription failed: {e}")
                ui.notify("FluidVoice", f"Transcription failed: {e}",
                          enabled=self.cfg["notifications"]["enabled"])
                wav.unlink(missing_ok=True)
                return
            pipeline = self._pipeline_factory(self.cfg, backend)
            out = pipeline.run(wav, app_hint, mode=mode,
                               rewrite_context=rewrite_context) or {}
            self.last_result = out
        finally:
            self.busy = False
            self._close_closing_display()
        # Turn 1 runs AFTER busy clears, so there is no busy-flag race with
        # the hotkey-confirm handoff below.
        if mode == "command" and out.get("mode") == "command":
            self._begin_command(str(out.get("text", "")))

    # -- command mode ---------------------------------------------------------

    def _begin_command(self, instruction: str) -> None:
        """Turn 1: ask the model for the first proposal (background thread;
        the user is not blocked - not even by the LLM latency)."""
        from . import command as command_mod

        def _work():
            factory = self._command_session_factory or command_mod.CommandSession
            session = factory(self.cfg)
            try:
                proposal = session.start(instruction)
            except command_mod.CommandError as e:
                with self._lock:
                    self.busy = False
                log(f"command mode failed: {e}")
                ui.notify("FluidVoice", f"Command mode failed: {e}",
                          enabled=self.cfg["notifications"]["enabled"])
                return
            if proposal is None:
                with self._lock:
                    self.busy = False
                ui.notify("FluidVoice",
                          session.summary or "Command mode: nothing to run.",
                          enabled=self.cfg["notifications"]["enabled"])
                return
            with self._lock:                 # atomic handoff to the pending state
                self._command_session = session
                self._command_pending = True
                self.busy = False            # waiting for the user, not busy
            self._present_proposal(session, proposal)

        def _guarded():
            try:
                _work()
            except Exception as e:  # noqa: BLE001 - never strand `busy`
                log(f"command mode failed: {e}")
                ui.notify("FluidVoice", f"Command mode failed: {e}",
                          enabled=self.cfg["notifications"]["enabled"])
                self._end_command_session()

        with self._lock:
            if self.busy or self._command_pending:
                return
            self.busy = True
        threading.Thread(target=_guarded, name="fluidvoice-command",
                         daemon=True).start()

    def _present_proposal(self, session, proposal) -> None:
        """Awaiting-confirmation UX: pill, armed Escape grab, notification,
        confirm watchdog. Call with no lock held."""
        try:
            from .overlay import FluidOverlay, confirmation_pill_text
            rcfg = self.cfg["recording"]
            ov = FluidOverlay(raw_path=None,
                              bottom_offset=int(rcfg.get("preview_bottom_offset", 64)),
                              size="large")
            if ov.using_overlay:
                ov.show(confirmation_pill_text(proposal.command,
                                               proposal.purpose))
                ov.set_state("confirm")
                ov.start()
                self._command_display = ov
            else:
                ov.close()  # headless: the notification carries everything
        except Exception as e:  # noqa: BLE001 - never block confirmation
            log(f"WARN command pill unavailable: {e}")
        if self._command_hotkey:
            try:
                self._command_hotkey.set_recording(True)  # arm Escape grab
            except Exception:
                pass
        purpose = proposal.purpose or ""
        body = (f"{purpose}\n" if purpose else "") \
            + f"$ {proposal.command}\n" \
            + "Press the command hotkey to run · Esc to cancel"
        ui.notify("FluidVoice — run this command?", body,
                  enabled=self.cfg["notifications"]["enabled"])
        self._command_timer = threading.Timer(
            float(self.cfg["command"].get("confirm_timeout_s", 120.0)),
            self._on_confirm_timeout)
        self._command_timer.daemon = True
        self._command_timer.start()

    def _confirm_pending_command(self) -> None:
        """Hotkey-confirmed: execute (the only path into CommandSession.confirm),
        then either present the next proposal or finish."""
        with self._lock:
            if not self._command_pending or self.busy or self.recording:
                return
            self._command_pending = False
            self.busy = True                 # atomic with the flag clear
        session = self._command_session      # never None while pending
        self._teardown_pending_ux()

        def _work():
            from . import command as command_mod
            try:
                proposal = session.confirm()
            except command_mod.CommandError as e:
                log(f"command mode failed: {e}")
                ui.notify("FluidVoice", f"Command mode failed: {e}",
                          enabled=self.cfg["notifications"]["enabled"])
                self._end_command_session()
                return
            outcome = session.executed[-1] if session.executed else None
            if outcome is not None:          # result via notification + history
                brief = (outcome.output or outcome.error or "").strip()[:200]
                ui.notify("FluidVoice",
                          f"$ {outcome.command} → exit {outcome.exit_code}"
                          + (f"\n{brief}" if brief else ""),
                          enabled=self.cfg["notifications"]["enabled"])
            if proposal is None:
                ui.notify("FluidVoice",
                          (session.summary or "Command finished.")
                          + (" (step limit reached)" if session.exhausted
                             else ""),
                          enabled=self.cfg["notifications"]["enabled"])
                self._end_command_session()
                return
            with self._lock:
                self._command_pending = True
                self.busy = False
            self._present_proposal(session, proposal)

        def _guarded():
            try:
                _work()
            except Exception as e:  # noqa: BLE001 - never strand `busy`
                log(f"command mode failed: {e}")
                ui.notify("FluidVoice", f"Command mode failed: {e}",
                          enabled=self.cfg["notifications"]["enabled"])
                self._end_command_session()

        threading.Thread(target=_guarded, name="fluidvoice-command",
                         daemon=True).start()

    def cancel_pending_command(self) -> None:
        """Escape on a pending proposal (or a test): nothing executes."""
        with self._lock:
            if not self._command_pending:
                return
            self._command_pending = False
        session, self._command_session = self._command_session, None
        self._teardown_pending_ux()
        if session is not None:
            session.cancel()
        ui.notify("FluidVoice", "Command cancelled",
                  enabled=self.cfg["notifications"]["enabled"])

    def _on_confirm_timeout(self) -> None:
        if self._command_pending:
            self.cancel_pending_command()
            ui.notify("FluidVoice", "Command mode: confirmation timed out",
                      enabled=self.cfg["notifications"]["enabled"])

    def _teardown_pending_ux(self) -> None:
        if self._command_timer:
            self._command_timer.cancel()
            self._command_timer = None
        if self._command_hotkey:
            try:
                self._command_hotkey.set_recording(False)
            except Exception:
                pass
        display, self._command_display = self._command_display, None
        if display is not None:
            try:
                display.close()
            except Exception:
                pass

    def _end_command_session(self) -> None:
        with self._lock:
            self._command_pending = False
            self.busy = False
        self._command_session = None
        self._teardown_pending_ux()
