"""Global hotkey on X11 via XGrabKey (python-xlib).

- "toggle" mode: every KeyPress of the hotkey fires the callback.
  Works with modifier-only keys (Right_Control, Right_Alt, ...).
- "hold" mode (push-to-talk): KeyPress starts, KeyRelease stops. Requires
  a non-modifier key. Falls back to toggle for modifier-only keys.
  Keys typed while holding PASS THROUGH to the focused app natively:
  the hold opens by releasing the XGrabKey activation (which by X11
  semantics grabs the whole keyboard for the key's press-to-release
  duration) and re-arming it when the hold ends. The release itself is
  detected by polling query_keymap() - auto-repeat-proof, since the ~30 Hz
  synthetic KeyRelease+KeyPress pairs of a held key never clear its bit.
  (An earlier XTEST ungrab->inject->re-grab replay design was abandoned:
  live Xorg 21.1 silently drops XTEST fakes that match the current key
  state - the original event already flipped it - so replayed presses
  are deduped away and never reach the app.)
"""
from __future__ import annotations

import threading

from Xlib import X, XK
from Xlib.display import Display

MODIFIER_MASKS = {
    "ctrl": X.ControlMask,
    "alt": X.Mod1Mask,
    "shift": X.ShiftMask,
    "super": X.Mod4Mask,
}
# Lock states that would otherwise defeat the grab (Num/Caps/Scroll)
_LOCK_MASKS = [0, X.Mod2Mask, X.LockMask, X.Mod5Mask,
               X.Mod2Mask | X.LockMask, X.Mod2Mask | X.Mod5Mask,
               X.LockMask | X.Mod5Mask, X.Mod2Mask | X.LockMask | X.Mod5Mask]

MODIFIER_ONLY_KEYSYMS = {
    XK.XK_Shift_L, XK.XK_Shift_R, XK.XK_Control_L, XK.XK_Control_R,
    XK.XK_Alt_L, XK.XK_Alt_R, XK.XK_Super_L, XK.XK_Super_R,
    XK.XK_Meta_L, XK.XK_Meta_R, XK.XK_Hyper_L, XK.XK_Hyper_R,
    getattr(XK, "XK_ISO_Level3_Shift", None),
    getattr(XK, "XK_ISO_Level5_Shift", None),
} - {None}

# Upstream macOS: the cancel shortcut (Escape) only acts while the overlay
# is up - i.e. dictation in progress. Same here: the cancel key is grabbed
# only while recording, so an idle daemon never swallows Escape.
DEFAULT_CANCEL_KEY = "Escape"


class HotkeyError(RuntimeError):
    pass


# Verdicts for one keyboard event seen during a hold cycle (see
# classify_hold_event). In the native-passthrough design only ABORT is
# consumed by the hold loop; REPLAY-classified keys flow straight to the
# focused app and are never delivered to us at all.
_HOLD_END, _HOLD_ABORT, _HOLD_REPLAY, _HOLD_IGNORE = "end", "abort", "replay", "ignore"


def classify_hold_event(etype, detail, hotkey_keycode, escape_keycode) -> str:
    """Pure: how _hold_cycle should treat one keyboard event.

    - KeyRelease(hotkey)            -> end
    - KeyPress(escape_keycode)      -> abort   (cancel recording)
    - Key{Press,Release}(anything else incl. modifiers) -> replay
      (delivered natively to the focused app; the hold loop ignores them)
    - hotkey KeyPress (auto-repeat), escape KeyRelease, non-key events,
      None details                  -> ignore
    escape_keycode may be None (cancel disabled) -> escape is a normal key.
    """
    if etype not in (X.KeyPress, X.KeyRelease) or detail is None:
        return _HOLD_IGNORE
    if etype == X.KeyRelease:
        if detail == hotkey_keycode:
            return _HOLD_END
        if escape_keycode is not None and detail == escape_keycode:
            return _HOLD_IGNORE  # the aborting press already ended the hold
        return _HOLD_REPLAY
    if etype == X.KeyPress:
        if escape_keycode is not None and detail == escape_keycode:
            return _HOLD_ABORT
        if detail == hotkey_keycode:
            return _HOLD_IGNORE  # auto-repeat press of the held hotkey
    return _HOLD_REPLAY


# Friendly aliases -> X11 keysym names (macOS-style modifiers etc.)
_KEY_ALIASES = {
    "right_control": "Control_R", "left_control": "Control_L",
    "right_ctrl": "Control_R", "left_ctrl": "Control_L",
    "right_alt": "Alt_R", "left_alt": "Alt_L", "right_option": "Alt_R",
    "left_option": "Alt_L", "right_command": "Super_R", "left_command": "Super_L",
    "right_super": "Super_R", "left_super": "Super_L", "super": "Super_L",
    "right_shift": "Shift_R", "left_shift": "Shift_L",
    "esc": "Escape", "return": "Return", "enter": "Return",
}


def resolve_keysym(name: str) -> int:
    keysym = XK.string_to_keysym(name)
    if keysym == X.NoSymbol:
        alias = _KEY_ALIASES.get(name.strip().lower().replace(" ", "_"))
        if alias:
            keysym = XK.string_to_keysym(alias)
    if keysym == X.NoSymbol:
        # "page up" -> "Page_Up", "right control" -> "Right_Control"
        normalized = "_".join(p.capitalize() for p in name.strip().split())
        keysym = XK.string_to_keysym(normalized)
    if keysym == X.NoSymbol:
        raise HotkeyError(f"unknown key name '{name}'")
    return keysym


class HotkeyListener:
    """Grabs the hotkey and invokes callbacks from its own thread."""

    def __init__(self, key: str, modifiers: list[str], mode: str,
                 on_toggle, on_cancel=None, cancel_key: str | None = None,
                 display_name: str | None = None):
        self.key = key
        self.mode = mode
        self.on_toggle = on_toggle
        self.on_cancel = on_cancel
        self.cancel_key = cancel_key
        self.display_name = display_name
        self._mods = sum(MODIFIER_MASKS.get(m, 0) for m in modifiers)
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._display: Display | None = None
        self._keycode = 0
        self._cancel_keycode: int | None = None
        self._escape_keycode: int | None = None
        self._want_cancel = False   # recording active -> grab the cancel key
        self._cancel_grabbed = False
        self._cancel_grab_warned = False
        self._summary: list[str] = []

    # -- setup ---------------------------------------------------------------

    def _keycode_for(self, keysym: int) -> int:
        assert self._display is not None
        code = self._display.keysym_to_keycode(keysym)
        return code or 0

    def _grab(self, keycode: int) -> None:
        assert self._display is not None
        root = self._display.screen().root
        for extra in _LOCK_MASKS:
            root.grab_key(keycode, self._mods | extra, False,
                          X.GrabModeAsync, X.GrabModeAsync)

    def _resolve_cancel(self) -> str:
        """Config value -> keysym name. None/"" mean the macOS default
        (Escape) - important for upgrade migration, since old templates
        wrote cancel_key = "" into saved configs. "none"/"off" disables."""
        raw = "" if self.cancel_key is None else self.cancel_key.strip()
        if not raw:
            return DEFAULT_CANCEL_KEY
        if raw.lower() in ("none", "off", "disabled"):
            return ""
        return raw

    def setup(self) -> list[str]:
        try:
            self._display = Display(self.display_name)
        except Exception as e:
            raise HotkeyError(f"cannot open X display ({e}) - is this an X11 session?") from e
        self._keycode = self._keycode_for(resolve_keysym(self.key))
        if not self._keycode:
            raise HotkeyError(f"key '{self.key}' has no keycode on this keymap")
        self._grab(self._keycode)
        # cancel acts ONLY while recording (macOS overlay-up semantics)
        cancel = self._resolve_cancel()
        self._cancel_keycode = self._keycode_for(resolve_keysym(cancel)) \
            if cancel else None
        self._cancel_grabbed = False
        self._escape_keycode = self._keycode_for(XK.XK_Escape)
        self._display.sync()
        self._summary = [f"hotkey {self.key} = keycode {self._keycode}, "
                         f"modifiers {self._mods:#x}, mode {self.mode}"
                         + (f", cancel {cancel} while recording" if cancel
                            else ", cancel disabled")]
        return self._summary

    # -- loop ----------------------------------------------------------------

    def start(self) -> None:
        if self._thread:
            return
        self.setup()
        self._thread = threading.Thread(target=self._run, name="fluidvoice-hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._display:
            try:
                self._display.close()
            except Exception:
                pass

    @property
    def summary(self) -> list[str]:
        return list(self._summary)

    def _run(self) -> None:  # pragma: no cover - needs a real X server
        d = self._display
        assert d is not None
        keysym = resolve_keysym(self.key)
        if self.mode == "hold" and keysym in MODIFIER_ONLY_KEYSYMS:
            self.mode = "toggle"  # push-to-talk needs a non-modifier key
        try:
            while not self._stop_flag.is_set():
                self._sync_cancel_grab()
                if d.pending_events() == 0:
                    self._stop_flag.wait(0.01)  # poll: responsive to grabs/stop
                    continue
                try:
                    event = d.next_event()
                except Exception:
                    break
                if getattr(event, "type", None) != X.KeyPress:
                    continue
                detail = getattr(event, "detail", None)
                if detail is None:
                    continue
                if self._cancel_keycode and detail == self._cancel_keycode:
                    self._safe(self.on_cancel)
                    continue
                if detail != self._keycode:
                    continue
                if self.mode == "hold":
                    self._hold_cycle(d, detail)
                else:
                    self._safe(self.on_toggle)
        finally:
            try:
                d.close()
            except Exception:
                pass

    def set_recording(self, active: bool) -> None:
        """Tell the listener dictation started/stopped; the cancel key is
        grabbed only while recording (macOS parity: Escape dismisses the
        overlay and discards, and does nothing when idle)."""
        self._want_cancel = bool(active)

    def _sync_cancel_grab(self) -> None:
        if self._display is None or not self._cancel_keycode:
            return
        if self._want_cancel == self._cancel_grabbed:
            return
        root = self._display.screen().root
        try:
            if self._want_cancel:
                self._grab(self._cancel_keycode)
            else:
                root.ungrab_key(self._cancel_keycode, X.AnyModifier)
            self._display.sync()
            self._cancel_grabbed = self._want_cancel
            self._cancel_grab_warned = False
        except Exception:
            # Another client holds a conflicting grab on the cancel key (a
            # second recording daemon on a shared desktop, a WM shortcut).
            # Retried every loop, so a transient holder self-heals; warn
            # once per recording so a dead cancel key is log-diagnosable.
            if self._want_cancel and not self._cancel_grab_warned:
                self._cancel_grab_warned = True
                print(f"[sayit-ermano] WARN cancel key '{self.cancel_key}' "
                      "grab failed - held by another client?", flush=True)
            # best-effort; cancel via CLI still works

    def _hotkey_still_down(self, d, keycode: int) -> bool:
        """True = the hotkey is still physically held, by query_keymap().
        Auto-repeat-proof: the ~30 Hz synthetic KeyRelease+KeyPress pairs a
        held key generates never clear its bit, so a clear bit is a REAL
        release. On any error: return True (keep holding; a closed display
        is handled by pending_events/next_event raising)."""
        try:
            km = d.query_keymap()
            return bool(km[keycode // 8] & (1 << (keycode % 8)))
        except Exception:
            return True

    def _hold_cycle(self, d: Display, keycode: int) -> None:
        """Push-to-talk with native key passthrough.

        The XGrabKey passive grab that fired this hold activates a FULL
        keyboard grab for the key's press-to-release duration (X11
        semantics) - historically that swallowed every other keystroke
        typed during the hold. This cycle instead RELEASES that activation
        immediately (ungrab_keyboard + ungrab_key), so every other key
        flows to the focused application natively: real events, no
        XTEST/XSendEvent injection, no fake-event dedup races. The hotkey's
        release is detected by polling query_keymap() (auto-repeat-proof);
        a passive Escape grab is armed just for the hold so Escape still
        cancels the recording (upstream semantics: a cancelled recording is
        discarded, not transcribed); the hotkey grab is re-armed on the way
        out. Deliberate divergences (documented in STATUS.md): typed keys
        do NOT interrupt the dictation (upstream clean-tap does), and the
        held hotkey's auto-repeat pairs reach the focused app like any
        other key. If the initial ungrab fails, keys keep being swallowed
        - the pre-passthrough behavior - but the hold still works."""
        root = d.screen().root
        self._safe(self.on_toggle)  # start
        aborted = False
        try:
            # Free the keyboard: the passive grab's activation holds it.
            try:
                d.ungrab_keyboard(X.CurrentTime)
                root.ungrab_key(keycode, X.AnyModifier)
                d.sync()
            except Exception:
                pass  # best-effort: worst case keys stay swallowed
            # Escape still cancels: arm a passive grab for the hold only
            # (its press-activation delivers Escape to us; other keys are
            # untouched by a passive grab that has not fired).
            if self._escape_keycode:
                try:
                    root.grab_key(self._escape_keycode, X.AnyModifier, False,
                                  X.GrabModeAsync, X.GrabModeAsync)
                except Exception:
                    pass  # best-effort: cancel via CLI still works
            try:
                while not self._stop_flag.is_set():
                    # Release detection: a clear keymap bit is a real
                    # release (auto-repeat never clears it).
                    if not self._hotkey_still_down(d, keycode):
                        break
                    # Escape (or anything the escape-grab activation
                    # delivered to us) - the only events we can see now.
                    try:
                        if d.pending_events():
                            event = d.next_event()
                            if classify_hold_event(
                                    getattr(event, "type", None),
                                    getattr(event, "detail", None),
                                    keycode, self._escape_keycode) == _HOLD_ABORT:
                                aborted = True
                                break
                    except Exception:
                        break  # display closed / stop() - end the hold
                    self._stop_flag.wait(0.02)  # ~50 Hz poll: stop-responsive
            finally:
                if self._escape_keycode:
                    try:
                        root.ungrab_key(self._escape_keycode, X.AnyModifier)
                    except Exception:
                        pass
                try:
                    self._grab(keycode)  # re-arm the dictation hotkey
                except Exception:
                    pass
        finally:
            try:
                d.ungrab_keyboard(X.CurrentTime)  # release escape activation
            except Exception:
                pass
        if aborted:
            self._safe(self.on_cancel)
        else:
            self._safe(self.on_toggle)  # stop and transcribe

    def _safe(self, cb) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass
