"""Input-device monitoring: poll pactl sources, diff the list, and
priority-match mic names for automatic switching.

A ~3 s `pactl list short sources` diff poll (no long-lived `pactl subscribe`
subprocess to parse; works on PipeWire and PulseAudio alike). The monitor
hands every post-baseline poll to `on_change(added, removed, current)` —
even diff-empty ones — so consumers can retry decisions on every tick
without their own pending state. Matching is case-insensitive substring of
the source name, first pattern wins (pattern order beats listing order).
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Callable

POLL_INTERVAL = 3.0


def list_source_names() -> list[str]:
    """Names from `pactl list short sources` (tab-separated; column 1 is
    the name). `.monitor` sources excluded. Returns [] on any failure (no
    pactl, timeout) — polling must never raise."""
    try:
        out = subprocess.run(["pactl", "list", "short", "sources"],
                             capture_output=True, text=True,
                             timeout=3).stdout
    except Exception:
        return []
    names: list[str] = []
    for line in (out or "").splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        name = fields[1].strip()
        if name and not name.endswith(".monitor"):
            names.append(name)
    return names


def priority_rank(name: str, patterns: list[str]) -> int | None:
    """Index of the first pattern matching `name` (case-insensitive
    substring); None when no pattern matches."""
    low = name.lower()
    for i, pattern in enumerate(patterns):
        if pattern.lower() in low:
            return i
    return None


def match_priority(patterns: list[str], names: list[str]) -> str | None:
    """The best source for a switch: for each pattern in order, the first
    name in listing order that matches it; None when nothing matches."""
    for pattern in patterns:
        low = pattern.lower()
        for name in names:
            if low in name.lower():
                return name
    return None


def sort_by_priority(mics: list[dict], patterns: list[str]) -> list[dict]:
    """Stable sort for mic menus: matched mics first ordered by
    (rank, original listing index); unmatched keep listing order after."""
    def key(item):
        index, mic = item
        rank = priority_rank(str(mic.get("name", "")), patterns)
        return (0, rank, index) if rank is not None else (1, 0, index)

    return [mic for _i, mic in sorted(enumerate(mics), key=key)]


class MicMonitor:
    """Diff-poll sources every `interval` seconds and hand every poll to
    `on_change(added, removed, current)` after the baseline poll. The
    baseline itself does NOT fire the callback."""

    def __init__(self,
                 on_change: Callable[[list[str], list[str], list[str]], None],
                 *,
                 interval: float = POLL_INTERVAL,
                 poll: Callable[[], list[str]] | None = None,
                 log: Callable[[str], None] = (lambda m: None)):
        self._on_change = on_change
        self._interval = interval
        self._default_poll = poll is None
        self._poll = poll or list_source_names
        self._log = log
        self.last_names: list[str] = []  # [] until the first poll
        self._started = False  # baseline taken?
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Baseline poll synchronously, then a daemon thread polling every
        `interval`. Returns False (logged) when the default poll is wanted
        but pactl is missing."""
        if self._default_poll and shutil.which("pactl") is None:
            self._log("mic monitoring unavailable (pactl not found)")
            return False
        self._stop_event.clear()
        self.poll_once()  # baseline: no callback
        self._thread = threading.Thread(target=self._loop,
                                        name="fluidvoice-micmon",
                                        daemon=True)
        self._thread.start()
        return True

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            self.poll_once()

    def stop(self) -> None:
        """Prompt (Event-based) and idempotent."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)

    def poll_once(self) -> None:
        """One poll: filter monitors, diff vs the previous poll, fire the
        callback. Errors from the poll or the callback are logged, never
        raised (a crashed watcher thread is a silent feature loss)."""
        try:
            names = [n for n in self._poll()
                     if not str(n).endswith(".monitor")]
        except Exception as e:  # noqa: BLE001 - polling must never raise
            self._log(f"mic poll failed ({e.__class__.__name__}: {e})")
            return
        if not self._started:
            self._started = True
            self.last_names = names
            return
        previous, self.last_names = self.last_names, names
        added = [n for n in names if n not in previous]      # listing order
        removed = [n for n in previous if n not in names]    # old order
        try:
            self._on_change(added, removed, list(names))
        except Exception as e:  # noqa: BLE001 - callback must not kill us
            self._log(f"mic change callback failed "
                      f"({e.__class__.__name__}: {e})")
