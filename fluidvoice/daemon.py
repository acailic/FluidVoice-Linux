"""The FluidVoiceLinux daemon: hotkey -> record -> transcribe -> polish -> type."""
from __future__ import annotations

import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import __version__, control, history as history_mod, paths
from . import backends, insertion, ui
from .ai.client import AIClient, AIError
from .audio_utils import duration_seconds, is_silent
from .config import load_config
from .processing import post_process
from .recorder import Recorder, RecorderError


def log(msg: str) -> None:
    print(f"[fluidvoice] {time.strftime('%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


class Daemon:
    def __init__(self, cfg: dict | None = None, use_hotkey: bool = True,
                 use_sounds: bool = True):
        self.cfg = cfg or load_config()
        self.use_hotkey = use_hotkey
        self.use_sounds = use_sounds
        self.recorder = Recorder(
            command=self.cfg["recording"]["command"],
            device=self.cfg["recording"].get("device", ""),
            sample_rate=self.cfg["recording"].get("sample_rate", 16000),
        )
        self.backend = None  # lazy: loads model on first use
        self.recording = False
        self.busy = False  # transcription/insertion in flight
        self.last_result: dict = {}
        self._app_hint: str | None = None
        self._recording_started = 0.0
        self._watchdog: threading.Timer | None = None
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def run(self) -> None:
        log(f"FluidVoiceLinux v{__version__} starting")
        notify_on = self.cfg["notifications"]["enabled"]
        try:
            self.backend = backends.load_backend(self.cfg)
        except Exception as e:
            log(f"WARN speech backend not ready yet ({e}); will retry on first use")
            self.backend = None

        self._hotkey = None
        if self.use_hotkey:
            self._start_hotkey(notify_on)

        ready = threading.Event()
        self._srv = control.serve(self.handle_request, ready=ready)
        ready.wait(timeout=5)
        log(f"control socket: {paths.socket_path()}")
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
        if self._watchdog:
            self._watchdog.cancel()
        if getattr(self, "_hotkey", None):
            self._hotkey.stop()
        sock = getattr(self, "_srv", None)
        if sock:
            try:
                sock.close()
            except OSError:
                pass
            paths.socket_path().unlink(missing_ok=True)

    def _start_hotkey(self, notify_on: bool) -> None:
        from .hotkey import HotkeyError, HotkeyListener
        hk = self.cfg["hotkey"]
        try:
            self._hotkey = HotkeyListener(
                key=hk["key"], modifiers=hk.get("modifiers", []),
                mode=hk.get("mode", "toggle"),
                on_toggle=self.toggle,
                on_cancel=self.cancel,
            )
            self._hotkey.start()
            for line in self._hotkey.summary:
                log(line)
        except HotkeyError as e:
            log(f"WARN hotkey unavailable: {e}")
            ui.notify("FluidVoice", f"Hotkey unavailable: {e}\n"
                      "Bind a DE shortcut to `fluidvoice toggle` instead.",
                      timeout_ms=8000, enabled=notify_on)

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
            return {"ok": True, "recording": self.recording, "busy": self.busy,
                    "backend": self.backend.name if self.backend else None,
                    "version": __version__}
        return {"ok": False, "error": f"unknown action {action!r}"}

    # -- dictation -----------------------------------------------------------

    def toggle(self) -> bool:
        with self._lock:
            if self.recording:
                self._stop_recording_locked()
                return False
            if self.busy:
                log("still processing previous dictation; ignoring toggle")
                return self.recording
            self._start_recording_locked()
            return True

    def _start_recording_locked(self) -> None:
        notify_on = self.cfg["notifications"]["enabled"]
        sounds_on = self.use_sounds and self.cfg["sounds"]["enabled"]
        self._app_hint = insertion.active_window_class()
        fd, tmp = tempfile.mkstemp(prefix="fluidvoice-", suffix=".wav")
        os.close(fd)
        try:
            self.recorder.start(Path(tmp))
        except RecorderError as e:
            log(f"recorder error: {e}")
            ui.notify("FluidVoice", f"Recording failed: {e}", enabled=notify_on)
            Path(tmp).unlink(missing_ok=True)
            return
        self.recording = True
        self._recording_started = time.monotonic()
        ui.play_sound("start", self.cfg["sounds"]["volume"], sounds_on)
        log(f"recording (app={self._app_hint or '?'})")
        max_s = float(self.cfg["recording"].get("max_seconds", 300))
        self._watchdog = threading.Timer(max_s, self._auto_stop)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _auto_stop(self) -> None:
        if self.recording:
            log("max duration reached, stopping")
            self.toggle()

    def _stop_recording_locked(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None
        wav = self.recorder.stop()
        self.recording = False
        sounds_on = self.use_sounds and self.cfg["sounds"]["enabled"]
        ui.play_sound("stop", self.cfg["sounds"]["volume"], sounds_on)
        if wav is None or not Path(wav).exists() or Path(wav).stat().st_size < 200:
            log("no audio captured")
            Path(wav or "").unlink(missing_ok=True)
            return
        threading.Thread(target=self._process, args=(Path(wav), self._app_hint),
                         daemon=True).start()

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
            self.backend = backends.load_backend(self.cfg)
            log(f"speech backend: {self.backend.name}")
        return self.backend

    def _process(self, wav: Path, app_hint: str | None) -> None:
        self.busy = True
        notify_on = self.cfg["notifications"]["enabled"]
        started = time.monotonic()
        try:
            duration = duration_seconds(str(wav))
            if self.cfg["recording"].get("skip_silent") and duration <= 4.0 and is_silent(str(wav)):
                log("silent recording skipped")
                wav.unlink(missing_ok=True)
                return
            try:
                backend = self._ensure_backend()
                result = backend.transcribe(wav, language=self.cfg["general"]["language"])
            except Exception as e:
                log(f"transcription failed: {e}")
                ui.notify("FluidVoice", f"Transcription failed: {e}", enabled=notify_on)
                wav.unlink(missing_ok=True)
                return
            raw = result.get("text", "")
            if not raw:
                log("empty transcription")
                wav.unlink(missing_ok=True)
                return
            text = post_process(raw, self.cfg, app_hint=app_hint)

            ai_used = False
            if self.cfg["ai"].get("enabled"):
                try:
                    client = AIClient(self.cfg)
                    text = client.polish(text)
                    ai_used = True
                except AIError as e:
                    log(f"AI polish failed ({e}); using raw transcription")

            try:
                strategy = insertion.insert_text(text, self.cfg)
            except insertion.InsertError as e:
                log(f"insertion failed: {e}")
                ui.notify("FluidVoice", f"Could not type text: {e}\n"
                          f"(copied to clipboard if possible)", enabled=notify_on)
                _fallback_clipboard(text)
                strategy = "clipboard-fallback"

            self.last_result = {"raw": raw, "text": text, "ai": ai_used}
            log(f"typed ({strategy}, {len(text)} chars, {duration:.1f}s audio, "
                f"{time.monotonic() - started:.1f}s total): {text[:120]}")
            if self.cfg["history"].get("save"):
                history_mod.append(
                    {"ts": time.time(), "duration_s": round(duration, 2),
                     "raw": raw, "text": text, "ai": ai_used,
                     "backend": backend.name, "app": app_hint},
                    audio_src=wav if self.cfg["history"].get("save_audio") else None,
                    keep_audio=self.cfg["history"].get("save_audio", False),
                    budget_gb=self.cfg["history"].get("audio_budget_gb", 4.0),
                )
            wav.unlink(missing_ok=True)
        finally:
            self.busy = False


def _fallback_clipboard(text: str) -> None:
    try:
        import subprocess
        subprocess.Popen(["xclip", "-selection", "clipboard"],
                         stdin=subprocess.PIPE).communicate(text.encode())
    except Exception:
        pass
