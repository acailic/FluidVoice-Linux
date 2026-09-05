"""Text post-processing pipeline (port of FluidVoice's chain).

Order matches upstream: filler removal -> custom dictionary -> spoken
punctuation formatting ("literal comma" etc.). The slash/mention literal
squeeze (chat apps) runs LATER, after AI cleanup — see daemon.py
(DictationPipeline._after_ai_formatting) and processing/slash.py.
"""
from __future__ import annotations

from .dictionary import apply_custom_dictionary
from .fillers import remove_filler_words
from .punctuation import format_spoken_punctuation
from .slash import squeeze_slash_mentions  # noqa: F401 - re-export

__all__ = ["post_process", "squeeze_slash_mentions"]


def post_process(text: str, cfg: dict, app_hint: str | None = None) -> str:
    p = cfg.get("processing", {})
    if p.get("remove_filler_words", True):
        text = remove_filler_words(text, p.get("filler_words"))
    text = apply_custom_dictionary(text, p.get("dictionary") or [])
    if p.get("punctuation_enabled", True):
        text = format_spoken_punctuation(
            text,
            prefix=p.get("punctuation_prefix", "literal"),
            app_hint=app_hint,
            extra_actions=p.get("formatting_action_triggers"),
        )
    return text
