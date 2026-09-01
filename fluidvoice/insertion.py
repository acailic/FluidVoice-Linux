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


def insert_text(text: str, cfg: dict) -> str:
    """Insert `text` at the caret. Returns the strategy used."""
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
    insert_typed(text, delay)
    return "typed"


def clipboard_fallback(text: str) -> None:
    """Last resort when neither typing nor pasting worked: leave text on the clipboard."""
    if not shutil.which("xclip"):
        return
    try:
        _clipboard_write(text.encode())
    except Exception:
        pass
