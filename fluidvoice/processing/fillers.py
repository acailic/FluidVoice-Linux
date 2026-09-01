"""Whole-word filler removal (um, uh, ...) - ported from FluidVoice.

Semantics mirror upstream ASRService.removeFillerWords: split on single
spaces, trim Unicode punctuation from both ends of each token for the
comparison, drop matching tokens entirely, rejoin with single spaces.
"""
from __future__ import annotations

import unicodedata

from ..config import DEFAULT_FILLERS


def _trim_punct(token: str) -> str:
    start, end = 0, len(token)
    while start < end and unicodedata.category(token[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(token[end - 1]).startswith("P"):
        end -= 1
    return token[start:end]


def remove_filler_words(text: str, fillers: list[str] | None = None) -> str:
    fillers = fillers if fillers is not None else DEFAULT_FILLERS
    filler_set = {f.lower() for f in fillers if f and f.strip()}
    if not filler_set or not text:
        return text
    kept = [part for part in text.split(" ")
            if _trim_punct(part).lower() not in filler_set]
    return " ".join(kept)
