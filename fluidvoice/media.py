"""MPRIS media pause during dictation (upstream MediaPlaybackService
semantics): pause only what is currently playing, resume only what we
paused, never double-resume. Uses playerctl; silent no-op without it.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Callable


def _run(args: list[str], timeout: float = 2.0) -> str:
    out = subprocess.run(["playerctl", *args], capture_output=True, text=True,
                         timeout=timeout)
    return (out.stdout or "").strip()


class MediaController:
    def __init__(self, log: Callable[[str], None] = (lambda m: None)):
        self._log = log
        self._paused: list[str] = []
        self._available = shutil.which("playerctl") is not None

    def pause_if_playing(self) -> bool:
        """Pause every playing MPRIS player; remember them for resume().
        Returns True if anything was paused."""
        if not self._available:
            return False
        try:
            players = [p for p in _run(["-l"]).splitlines() if p.strip()]
        except Exception:
            return False
        paused = []
        for player in players:
            try:
                if _run(["-p", player, "status"]) == "Playing":
                    _run(["-p", player, "pause"])
                    paused.append(player)
            except Exception:
                continue  # player vanished mid-loop - fine
        if paused:
            self._paused = paused
            self._log(f"paused media: {', '.join(paused)}")
        return bool(paused)

    def resume(self) -> None:
        """Resume exactly the players we paused, and only if still paused
        (never fight a manual pause or a double-resume)."""
        players, self._paused = self._paused, []
        if not players or not self._available:
            return
        for player in players:
            try:
                if _run(["-p", player, "status"]) == "Paused":
                    _run(["-p", player, "play"])
                    self._log(f"resumed media: {player}")
            except Exception:
                continue

    def reset(self) -> None:
        self._paused = []
