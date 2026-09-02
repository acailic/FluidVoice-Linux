"""GAAV formatting + SpokenSend parsing (ported from upstream ASRService).

GAAV ("for search queries, form fields, or casual text input"):
optionally lowercases the first letter and strips one trailing period.

SpokenSend: a trailing spoken phrase (default "send it") strips from the
transcript and asks the pipeline to press Enter after insertion. Speaking
"literal send it" keeps the words and disables sending for that utterance.
"""
from __future__ import annotations

import re


def apply_gaav(text: str, *, lowercase_first: bool, remove_trailing_period: bool) -> str:
    if not text:
        return text
    if remove_trailing_period and text.endswith("."):
        text = text[:-1]
    if lowercase_first and text[:1].isupper():
        text = text[:1].lower() + text[1:]
    return text


class SpokenSendResult:
    __slots__ = ("text", "should_send")

    def __init__(self, text: str, should_send: bool):
        self.text = text
        self.should_send = should_send


def parse_spoken_send(text: str, phrase: str = "send it") -> SpokenSendResult:
    """Strip a trailing send-phrase; honor the 'literal <phrase>' escape."""
    if not phrase:
        return SpokenSendResult(text, False)
    p = re.escape(phrase.strip())
    # "literal send it" at the end -> keep the words, do not send
    escape_re = re.compile(r"[ \t]*literal[ \t]+" + p + r"[ \t]*\.?[ \t]*$", re.IGNORECASE)
    if escape_re.search(text):
        return SpokenSendResult(escape_re.sub("", text).rstrip() + " " + phrase, False)
    strip_re = re.compile(r"[ \t]*,?[ \t]*" + p + r"[ \t]*\.?[ \t]*$", re.IGNORECASE)
    if strip_re.search(text):
        return SpokenSendResult(strip_re.sub("", text).rstrip(), True)
    return SpokenSendResult(text, False)
