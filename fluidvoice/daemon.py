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
from .audio_utils import duration_seconds, is_silent
from .config import load_config
from .processing import post_process
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
                 logger: Callable[[str], None] = log):
        self.cfg = cfg
        self.backend = backend
        self.inserter = inserter
        self.polisher = polisher  # None -> build AIClient lazily when enabled
        self.history_writer = history_writer  # None -> history_mod.append
        self.log = logger
        self.notify = lambda title, body="": ui.notify(title, body, enabled=cfg["notifications"]["enabled"])

    # -- steps ------------------------------------------------------------

    def _should_skip(self, wav: Path, duration: float) -> bool:
        if not self.cfg["recording"].get("skip_silent"):
            return False
        return duration <= 4.0 and is_silent(str(wav))

    def _transcribe(self, wav: Path) -> dict:
        return self.backend.transcribe(wav, language=self.cfg["general"]["language"])

    def _polish(self, text: str) -> tuple[str, bool]:
        """Returns (text, ai_used) - falls back to the raw text on AI errors."""
        if not self.cfg["ai"].get("enabled"):
            return text, False
        polisher = self.polisher or AIClient(self.cfg).polish
        try:
            return polisher(text), True
        except AIError as e:
            self.log(f"AI polish failed ({e}); using raw transcription")
            return text, False

    def _insert(self, text: str) -> str:
        try:
            return self.inserter(text, self.cfg)
        except insertion.InsertError as e:
            self.log(f"insertion failed: {e}")
            self.notify("FluidVoice", f"Could not type text: {e}\n(copied to clipboard instead)")
            insertion.clipboard_fallback(text)
            return "clipboard-fallback"

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

    def run(self, wav: Path, app_hint: str | None) -> dict | None:
        """Returns the result dict (raw/text/ai/strategy) or None if nothing was typed."""
        started = time.monotonic()
        try:
            duration = duration_seconds(str(wav))
            if self._should_skip(wav, duration):
                self.log("silent recording skipped")
                return None
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
            polished, ai_used = self._polish(text)
            strategy = self._insert(polished)
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
        self.backend: Any = None  # lazy: loads model on first use
        self.recording = False
        self.busy = False  # transcription/insertion in flight
        self.last_result: dict = {}
        self._app_hint: str | None = None
        self._watchdog: threading.Timer | None = None
        self._lock = threading.Lock()
        self._hotkey = None
        self._srv: Any = None
        self.webui: Any = None
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

        if self.use_hotkey:
            self._start_hotkey()

        ready = threading.Event()
        self._srv = control.serve(self.handle_request, ready=ready)
        ready.wait(timeout=5)
        log(f"control socket: {paths.socket_path()}")

        self.webui = None
        if self.cfg.get("server", {}).get("enabled", True):
            try:
                from .webui import WebUI
                self.webui = WebUI(daemon=self, cfg=self.cfg)
                port = self.webui.start()
                log(f"settings UI: http://127.0.0.1:{port} (`fluidvoice settings`)")
            except Exception as e:
                log(f"WARN settings UI unavailable: {e}")

        log("ready - press the hotkey to dictate "
            f"(or run `fluidvoice toggle`; config: {paths.config_file()})")

        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            while not stop.is_set():
                time.sleep(0.3)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        log("shutting down")
        if self.recording:
            self.recorder.cancel()
            self.recording = False
        if self._watchdog:
            self._watchdog.cancel()
        if self._hotkey:
            self._hotkey.stop()
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
            paths.socket_path().unlink(missing_ok=True)
        if self.webui:
            self.webui.stop()

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

    def _start_hotkey(self) -> None:
        from .hotkey import HotkeyError, HotkeyListener
        hk = self.cfg["hotkey"]
        try:
            self._hotkey = HotkeyListener(
                key=hk["key"], modifiers=hk.get("modifiers", []),
                mode=hk.get("mode", "toggle"),
                on_toggle=self.toggle,
                on_cancel=self.cancel,
                cancel_key=hk.get("cancel_key", ""),
            )
            self._hotkey.start()
            for line in self._hotkey.summary:
                log(line)
        except HotkeyError as e:
            log(f"WARN hotkey unavailable: {e}")
            ui.notify("FluidVoice", f"Hotkey unavailable: {e}\n"
                      "Bind a DE shortcut to `fluidvoice toggle` instead.",
                      timeout_ms=8000, enabled=self.cfg["notifications"]["enabled"])

    # -- control protocol ----------------------------------------------------

    def handle_request(self, req: dict) -> dict:
        action = req.get("action")
        if action == "toggle":
            recording = self.toggle()
            return {"ok": True, "recording": recording}
        if action == "cancel":
            self.cancel()
            return {"ok": True, "recording": False, "cancelled": True}
        if action == "status":
            webui_port = self.webui.port if getattr(self, "webui", None) else None
            return {"ok": True, "recording": self.recording, "busy": self.busy,
                    "backend": self.backend.name if self.backend else None,
                    "version": __version__, "webui_port": webui_port}
        return {"ok": False, "error": f"unknown action {action!r}"}

    # -- dictation -----------------------------------------------------------

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
        ui.play_sound("start", self.cfg["sounds"]["volume"],
                      self.use_sounds and self.cfg["sounds"]["enabled"])
        log(f"recording (app={self._app_hint or '?'})")
        max_s = float(self.cfg["recording"].get("max_seconds", 300))
        self._watchdog = threading.Timer(max_s, self._auto_stop)
        self._watchdog.daemon = True
        self._watchdog.start()

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
        # Stop cue fires at capture stop (upstream behavior), before waiting
        # for the recorder process to flush and exit.
        ui.play_sound("stop", self.cfg["sounds"]["volume"],
                      self.use_sounds and self.cfg["sounds"]["enabled"])
        wav = self.recorder.stop()
        self.recording = False
        if wav is None or not Path(wav).exists() or Path(wav).stat().st_size < 200:
            log("no audio captured")
            if wav:
                Path(wav).unlink(missing_ok=True)
            return
        self._process_thread = threading.Thread(
            target=self._process, args=(Path(wav), self._app_hint), daemon=True)
        self._process_thread.start()

    def cancel(self) -> None:
        with self._lock:
            if not self.recording:
                return
            if self._watchdog:
                self._watchdog.cancel()
                self._watchdog = None
            self.recorder.cancel()
            self.recording = False
        log("cancelled")
        ui.notify("FluidVoice", "Cancelled", enabled=self.cfg["notifications"]["enabled"])

    # -- pipeline ------------------------------------------------------------

    def _ensure_backend(self):
        if self.backend is None:
            self.backend = self._backend_factory(self.cfg)
            log(f"speech backend: {self.backend.name}")
        return self.backend

    def _process(self, wav: Path, app_hint: str | None) -> None:
        self.busy = True
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
            self.last_result = pipeline.run(wav, app_hint) or {}
        finally:
            self.busy = False
