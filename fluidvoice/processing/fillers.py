"""Whole-word filler removal (um, uh, ...) - ported from FluidVoice."""
from __future__ import annotations

import re

from ..config import DEFAULT_FILLERS

_STRIP_PUNCT = "".join(sorted(set(re.escape(c) for c in ".,!?;:'\"()[]{}-—–…")))


def remove_filler_words(text: str, fillers: list[str] | None = None) -> str:
    fillers = fillers if fillers is not None else DEFAULT_FILLERS
    filler_set = {f.lower() for f in fillers if f and f.strip()}
    if not filler_set:
        return text
    parts = re.split(r"(\s+)", text)  # keep exact whitespace
    out: list[str] = []
    for part in parts:
        if not part or part.isspace():
            out.append(part)
            continue
        core = part.strip(_STRIP_PUNCT)
        if core.lower() in filler_set:
            continue  # drop the filler (its adjacent whitespace stays)
        out.append(part)
    # Dropping tokens can leave doubled whitespace; collapse horizontal runs.
    result = "".join(out)
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()
