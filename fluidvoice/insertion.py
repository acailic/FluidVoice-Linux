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
from typing import Callable


class InsertError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Paste timing constants (module-level, read at call time so tests can
# monkeypatch them; live-observed on a GNOME/X11 desktop running CopyQ 7.1.0
# + the clipboard-indicator GNOME extension - see docs/STATUS.md).
# ---------------------------------------------------------------------------
PASTE_QUIESCE_S = 0.25          # eager readers land here (observed +0.00..0.01)
PASTE_VERIFY_TIMEOUT_S = 0.60   # post-keystroke read cap
PASTE_POLL_INTERVAL_S = 0.025   # granularity of selection-event waits
RESTORE_SETTLE_S = 0.12         # xclip fork serve latency after a restore write
LEGACY_SETTLE_S = 0.25          # today's fixed sleep (insertion.verify_paste = false)
VERIFY_LADDER_S = (0.10, 0.20, 0.30)  # fallback ladder when ownership is unavailable
RESTORE_VERIFY_RETRIES = 1
# Clipboard-manager hygiene markers advertised alongside the dictation text
# while we own the selection: x-kde-passwordManagerHint is the Klipper/
# GPaste/KeePassXC convention; the two application/x-copyq-* markers are
# honored by CopyQ 7.1.0 (live-verified: the item is NOT stored). The GNOME
# shell clipboard-indicator ignores all of them - residual, documented.
HYGIENE_TARGETS = (
    ("x-kde-passwordManagerHint", b"secret"),
    ("application/x-copyq-secret", b"1"),
    ("application/x-copyq-hidden", b"1"),
)


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


def _clipboard_snapshot() -> tuple[bytes | None, bool]:
    """The pre-paste clipboard as (bytes | None, is_text). is_text comes
    from one TARGETS probe (UTF8_STRING/text/plain/STRING) - a non-text
    previous (e.g. an image) is restored blind: never fail an insert over
    a clipboard we cannot read back."""
    previous = _clipboard_read()
    if previous is None:
        return None, False
    proc = _run(["xclip", "-o", "-selection", "clipboard", "-t", "TARGETS"],
                timeout=5)
    targets = proc.stdout.decode(errors="replace") if proc.returncode == 0 else ""
    is_text = any(t in targets for t in ("UTF8_STRING", "text/plain", "STRING"))
    return previous, is_text


def _make_hold(data: bytes, hygiene=HYGIENE_TARGETS):
    """A SelectionHold serving the paste payload + hygiene markers, or
    None when selection ownership is unavailable (no DISPLAY, X error,
    oversized payload) - the caller falls back to the legacy xclip flash."""
    if not _display_active():
        return None
    try:
        from .selection import SelectionHold, SelectionUnavailable
        return SelectionHold(data, hygiene)
    except SelectionUnavailable:
        return None
    except Exception:  # noqa: BLE001 - never let verification break pasting
        return None


def _clipboard_write(data: bytes) -> None:
    # xclip forks and serves the selection; give it a moment then detach.
    subprocess.Popen(["xclip", "-selection", "clipboard"],
                     stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL).communicate(data)
    time.sleep(0.15)


def _restore_clipboard(previous: bytes | None, prev_is_text: bool, *,
                       verify_text: bool, skip: bool,
                       on_notice: Callable[[str], None] | None) -> None:
    """Put the pre-paste clipboard bytes back. Blind unless verify_text
    (read-back compared, one retry). Never raises - an unverifiable restore
    warns via on_notice instead (the paste already landed; raising would
    make insert_text re-type and double-insert)."""
    if previous is None:
        return  # clipboard was empty before the paste
    if skip:
        return  # another client owns the clipboard now: their content wins
    for _attempt in range(1 + (RESTORE_VERIFY_RETRIES if verify_text else 0)):
        try:
            _clipboard_write(previous)
        except Exception:
            return  # restore itself failed; swallowed (today's behavior)
        time.sleep(RESTORE_SETTLE_S)
        if not verify_text or _clipboard_read() == previous:
            return
    if on_notice is not None:
        on_notice("Clipboard restore could not be verified - "
                  "your previous clipboard may be lost")


def insert_paste(text: str, *, key: str = "ctrl+v", verify: bool = True,
                 on_notice: Callable[[str], None] | None = None) -> None:
    """Clipboard paste with verify-then-restore.

    verify=True (insertion.verify_paste) owns the CLIPBOARD selection for
    the duration (python-xlib) instead of a blind xclip flash: hygiene
    marker targets are advertised so clipboard managers suppress the
    dictation, the paste keystroke is verified by observing the target
    read the selection, and only then is the previous clipboard restored
    (read-back checked, one retry). An unverified paste raises InsertError
    AFTER the restore so insert_text can fall back to typed insertion.
    verify=False keeps today's behavior exactly (fixed sleep + blind
    restore; terminal key still honored).
    """
    if not shutil.which("xclip"):
        raise InsertError("xclip is required for paste mode (sudo apt install xclip)")
    data = text.encode()
    previous, prev_is_text = _clipboard_snapshot()
    hold = _make_hold(data) if verify else None
    verified = False
    try:
        if hold is not None:
            known = hold.quiesce(PASTE_QUIESCE_S, interval=PASTE_POLL_INTERVAL_S)
        else:
            _clipboard_write(data)  # legacy flash (managers snapshot it)
        proc = _run(["xdotool", "key", "--clearmodifiers", key], timeout=10)
        if proc.returncode != 0:
            raise InsertError(f"paste keystroke failed: {proc.stderr.decode()[:200]}")
        if hold is not None:
            # ICCCM: while we own the selection, every read is a
            # SelectionRequest naming its requestor window - a window not
            # seen during the quiesce reading AFTER the keystroke means the
            # target app took the clipboard = the paste landed.
            verified = hold.wait_read(PASTE_VERIFY_TIMEOUT_S,
                                      exclude_windows=known,
                                      interval=PASTE_POLL_INTERVAL_S) is not None
        elif verify:
            for settle in VERIFY_LADDER_S:
                time.sleep(settle)
        else:
            time.sleep(LEGACY_SETTLE_S)
    finally:
        skip_restore = False
        if hold is not None:
            skip_restore = hold.lost_ownership  # user's fresh copy wins
            try:
                hold.release()
            except Exception:
                pass
        _restore_clipboard(previous, prev_is_text,
                           verify_text=hold is not None and prev_is_text,
                           skip=skip_restore, on_notice=on_notice)
    if hold is not None and not verified:
        err = InsertError("paste not verified: target did not read the clipboard")
        err.not_verified = True  # type: ignore[attr-defined]
        raise err


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


def insert_text(text: str, cfg: dict, wm_class: str | None = None,
                on_notice: Callable[[str], None] | None = None) -> str:
    """Insert `text` at the caret. Returns the strategy used.

    wm_class: the insertion target's WM_CLASS (None -> live lookup). In
    terminal apps (general.terminal_apps) pastes use ctrl+shift+v
    (insertion.terminal_paste_key - X11 terminals pass ctrl+v to the app)
    and typed insertions ending in a word character gain one trailing
    space (insertion.terminal_autocomplete_space) so autocomplete commits;
    the space is typing-only - clipboard copy and history keep the text
    without it. on_notice surfaces paste-fallback / restore warnings."""
    mode = cfg["insertion"]["mode"]
    threshold = cfg["insertion"].get("paste_threshold_chars", 1200)
    delay = cfg["insertion"].get("type_delay_ms", 8)
    wm = active_window_class() if wm_class is None else wm_class
    terminal = bool(wm and is_terminal_app(wm, cfg))
    use_paste = (mode == "paste" or len(text) > threshold or text.startswith("-"))
    if use_paste:
        key = (cfg["insertion"].get("terminal_paste_key", "ctrl+shift+v")
               if terminal else "ctrl+v")
        try:
            insert_paste(text, key=key,
                         verify=cfg["insertion"].get("verify_paste", True),
                         on_notice=on_notice)
            return "paste"
        except InsertError as e:
            if mode == "paste":
                raise
            if getattr(e, "not_verified", False) and on_notice is not None:
                on_notice("Paste did not land - typing instead")
    if cfg["insertion"].get("terminal_autocomplete_space", True):
        if terminal:
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
