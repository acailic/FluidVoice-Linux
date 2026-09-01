"""Global hotkey on X11 via XGrabKey (python-xlib).

- "toggle" mode: every KeyPress of the hotkey fires the callback.
  Works with modifier-only keys (Right_Control, Right_Alt, ...).
- "hold" mode (push-to-talk): KeyPress starts, KeyRelease stops. Implemented
  with a temporary keyboard grab so the release is visible; requires a
  non-modifier key. Falls back to toggle for modifier-only keys.
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


class HotkeyError(RuntimeError):
    pass


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
        alias = _KEY_ALIASES.get(name.strip().lower())
        if alias:
            keysym = XK.string_to_keysym(alias)
    if keysym == X.NoSymbol:
        normalized = "".join(p.capitalize() for p in name.replace(" ", "_").split("_"))
        keysym = XK.string_to_keysym(normalized)
    if keysym == X.NoSymbol:
        raise HotkeyError(f"unknown key name '{name}'")
    return keysym


class HotkeyListener:
    """Grabs the hotkey and invokes callbacks from its own thread."""

    def __init__(self, key: str, modifiers: list[str], mode: str,
                 on_toggle, on_cancel=None, display_name: str | None = None):
        self.key = key
        self.mode = mode
        self.on_toggle = on_toggle
        self.on_cancel = on_cancel
        self.display_name = display_name
        self._mods = sum(MODIFIER_MASKS.get(m, 0) for m in modifiers)
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._display: Display | None = None
        self._keycode = 0
        self._cancel_keycode: int | None = None
        self._escape_keycode: int | None = None
        self.cancel_key: str = ""
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

    def setup(self) -> list[str]:
        try:
            self._display = Display(self.display_name)
        except Exception as e:
            raise HotkeyError(f"cannot open X display ({e}) - is this an X11 session?") from e
        self._keycode = self._keycode_for(resolve_keysym(self.key))
        if not self._keycode:
            raise HotkeyError(f"key '{self.key}' has no keycode on this keymap")
        self._grab(self._keycode)
        if self.cancel_key:
            self._cancel_keycode = self._keycode_for(resolve_keysym(self.cancel_key))
            if self._cancel_keycode:
                self._grab(self._cancel_keycode)
        self._escape_keycode = self._keycode_for(XK.XK_Escape)
        self._display.sync()
        self._summary = [f"hotkey {self.key} = keycode {self._keycode}, "
                         f"modifiers {self._mods:#x}, mode {self.mode}"]
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
        return self._summary

    def _run(self) -> None:  # pragma: no cover - needs a real X server
        d = self._display
        assert d is not None
        keysym = resolve_keysym(self.key)
        if self.mode == "hold" and keysym in MODIFIER_ONLY_KEYSYMS:
            self.mode = "toggle"  # push-to-talk needs a non-modifier key
        try:
            while not self._stop_flag.is_set():
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

    def _hold_cycle(self, d: Display, keycode: int) -> None:
        """Push-to-talk: grab the keyboard until the hotkey is released."""
        root = d.screen().root
        try:
            root.grab_keyboard(False, X.GrabModeAsync, X.GrabModeAsync, X.CurrentTime)
        except Exception:
            self._safe(self.on_toggle)  # degrade to a single toggle
            return
        self._safe(self.on_toggle)  # start
        while not self._stop_flag.is_set():
            try:
                event = d.next_event()
            except Exception:
                break
            etype = getattr(event, "type", None)
            detail = getattr(event, "detail", None)
            if etype == X.KeyRelease and detail == keycode:
                break
            if etype == X.KeyPress and detail == self._escape_keycode:
                break  # aborts the hold; recording still stops below
        try:
            d.ungrab_keyboard(X.CurrentTime)
        except Exception:
            pass
        self._safe(self.on_toggle)  # stop

    def _safe(self, cb) -> None:
        if cb is None:
            return
        try:
            cb()
        except Exception:
            pass
