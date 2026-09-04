"""Text insertion into the focused app (X11): typed keystrokes or clipboard paste.

Mirrors FluidVoice's TypingService strategies:
- typed: xdotool type (keystroke simulation, "clipboard free insert")
- paste: clipboard + Ctrl+V with clipboard restore ("reliable paste")
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time


class InsertError(RuntimeError):
    pass


def _display_active() -> bool:
    return bool(os.environ.get("DISPLAY"))


def _run(args: list[str], timeout: float = 15.0, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, input=stdin, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise InsertError(f"required tool not found: {args[0]}") from None


def active_window_class() -> str | None:
    """WM_CLASS (or title) of the active window - the punctuation app hint."""
    if not (shutil.which("xdotool") and _display_active()):
        return None
    try:
        wid = _run(["xdotool", "getactivewindow"], timeout=3).stdout.decode().strip()
        if not wid:
            return None
        if shutil.which("xprop"):
            out = _run(["xprop", "-id", wid, "WM_CLASS"], timeout=3).stdout.decode()
            for part in reversed(re.findall(r'"([^"]*)"', out)):  # class is last
                if part:
                    return part
        name = _run(["xdotool", "getwindowname", wid], timeout=3).stdout.decode().strip()
        return name or None
    except Exception:
        return None


def insert_typed(text: str, delay_ms: int) -> None:
    # xdotool has no "--" guard for type; a leading dash would be parsed as an
    # option, so such texts go through the clipboard path instead.
    if text.startswith("-"):
        raise InsertError("text starts with '-' needs paste mode")
    proc = _run(["xdotool", "type", "--delay", str(max(0, delay_ms)),
                 "--clearmodifiers", text])
    if proc.returncode != 0:
        raise InsertError(f"xdotool type failed: {proc.stderr.decode()[:200]}")


def _clipboard_read() -> bytes | None:
    proc = _run(["xclip", "-o", "-selection", "clipboard"], timeout=5)
    if proc.returncode == 0:
        return proc.stdout
    return None  # empty clipboard


def _clipboard_write(data: bytes) -> None:
    # xclip forks and serves the selection; give it a moment then detach.
    subprocess.Popen(["xclip", "-selection", "clipboard"],
                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL).communicate(data)
    time.sleep(0.15)


def insert_paste(text: str) -> None:
    if not shutil.which("xclip"):
        raise InsertError("xclip is required for paste mode (sudo apt install xclip)")
    previous = _clipboard_read()
    try:
        _clipboard_write(text.encode())
        proc = _run(["xdotool", "key", "--clearmodifiers", "ctrl+v"], timeout=10)
        if proc.returncode != 0:
            raise InsertError(f"paste keystroke failed: {proc.stderr.decode()[:200]}")
        time.sleep(0.25)  # let the target app read the clipboard
    finally:
        if previous is not None:
            try:
                _clipboard_write(previous)
            except Exception:
                pass


def is_terminal_app(wm_class: str | None, cfg: dict) -> bool:
    """True when the WM_CLASS matches any general.terminal_apps entry
    (case-insensitive substring — the config drives both the spoken-send
    Enter blocklist and terminal autocomplete spacing)."""
    apps = cfg.get("general", {}).get("terminal_apps") or []
    if not wm_class:
        return False
    lowered = wm_class.lower()
    return any(p.lower() in lowered for p in apps)


def terminal_trailing_space(text: str) -> str:
    """One trailing space iff the text ends in a word character, so a
    terminal's autocomplete commits the last token (Linux adaptation —
    upstream strips trailing spaces in chat apps instead, :236-261).
    Idempotent: space/punctuation-ending and empty texts are unchanged."""
    if not text or not re.search(r"\w$", text):
        return text
    return text + " "


def insert_text(text: str, cfg: dict, wm_class: str | None = None) -> str:
    """Insert `text` at the caret. Returns the strategy used.

    wm_class: the insertion target's WM_CLASS (None -> live lookup). In
    terminal apps (general.terminal_apps) typed insertions ending in a word
    character gain one trailing space (insertion.terminal_autocomplete_space)
    so autocomplete commits; the space is typing-only — clipboard copy and
    history keep the text without it."""
    mode = cfg["insertion"]["mode"]
    threshold = cfg["insertion"].get("paste_threshold_chars", 1200)
    delay = cfg["insertion"].get("type_delay_ms", 8)
    use_paste = (mode == "paste" or len(text) > threshold or text.startswith("-"))
    if use_paste:
        try:
            insert_paste(text)
            return "paste"
        except InsertError:
            if mode == "paste":
                raise
    if cfg["insertion"].get("terminal_autocomplete_space", True):
        wm = active_window_class() if wm_class is None else wm_class
        if wm and is_terminal_app(wm, cfg):
            text = terminal_trailing_space(text)
    insert_typed(text, delay)
    return "typed"


def clipboard_fallback(text: str) -> None:
    """Last resort when neither typing nor pasting worked: leave text on the clipboard."""
    copy_to_clipboard(text)


def press_key(spec: str) -> None:
    """Press a key combo (e.g. 'enter', 'shift+enter') in the focused window."""
    proc = _run(["xdotool", "key", "--clearmodifiers", spec], timeout=5)
    if proc.returncode != 0:
        raise InsertError(f"key press failed: {proc.stderr.decode()[:200]}")


def copy_to_clipboard(text: str) -> None:
    """Put text on the clipboard without typing (upstream copyTranscriptionToClipboard)."""
    if not shutil.which("xclip"):
        return
    try:
        _clipboard_write(text.encode())
    except Exception:
        pass
