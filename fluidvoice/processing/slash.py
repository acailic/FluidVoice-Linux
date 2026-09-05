"""Slash-command / mention literal + spoken squeeze (chat-app formatting).

Port of Fluid-oss ``ASRService+DictationLiteralFormatting``:
``Sources/Fluid/Services/ASRService+DictationLiteralFormatting.swift`` —
slash regex ``:91-94``, spoken slash regex ``:96-99``, rejected slash tokens
``:101-109``, spoken lead-in words ``:111-114``, mention rejected tokens
``:141-146``, explicit spoken mention regex ``:121-124``, lowercase slash
replacement ``:283``, spoken-slash context gate ``:305-322``, mention name
validation ``:349-371`` (possessive guard ``:374-380``), whole-match skip on
any rejected token (upstream ``:289-297`` guards, applied per match).

Upstream formats only SPOKEN mentions ("at sign John", "tag John"); there
is no literal ``@ John`` rule upstream — the literal-``@`` pass here is a
port addition keyed on the ``@`` sigil; its name grammar, rejected-token
list and possessive guard mirror the explicit-mention pass. Upstream's
relaxed spoken form ("at John", app-gated to chat apps) is not ported; the
explicit spoken forms run unconditionally like the literal passes.
"""
from __future__ import annotations

import re

# upstream slashCommandRejectedTokens (:101-109, 53 tokens, verbatim)
SLASH_REJECTED_TOKENS = frozenset("""a an and as at back backslash be been being
bin by comma desktop documents dot downloads etc for forward from home in is
library local mark of on or period private question quote quotes semicolon
slash slashes source sources src the tmp to user users usr var volumes was were
with without""".split())

# upstream mentionRejectedTokens (:141-146, 25 tokens, verbatim)
MENTION_REJECTED_TOKENS = frozenset("""a an airport breakfast brunch class
dinner home hotel house lunch meeting night noon office place restaurant
school shop store the today tomorrow work yesterday""".split())

# upstream slashCommandSpokenLeadInWords (:111-114, 17 words, verbatim) -
# "slash fix" only squeezes after these verbs / sentence punctuation / start
SLASH_SPOKEN_LEAD_IN_WORDS = frozenset("""call choose do enter execute open
pick press run say select send start try type use write""".split())

# upstream slashCommandLiteralRegex (:91-94); Python \w ≈ [\p{L}\p{N}_]
_SLASH_RE = re.compile(
    r"(?<!\w)/\s+([A-Za-z][A-Za-z0-9_-]{1,39})(?![A-Za-z0-9_-])")
# upstream slashCommandSpokenRegex (:96-99): "slash fix"/"forward slash fix"
_SPOKEN_SLASH_RE = re.compile(
    r"(?<!\w)(?i:(?:forward\s+slash|slash))\s+"
    r"([A-Za-z][A-Za-z0-9_-]{1,39})(?![A-Za-z0-9_-])")
# literal-@ analog of upstream explicitMentionRegex (:121-124): 1-3 name
# tokens of [A-Za-z0-9_.-], first char a letter, internal spaces preserved
_MENTION_RE = re.compile(
    r"(?<![\w@])@\s+([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Za-z][A-Za-z0-9_.-]*){0,2})"
    r"(?![A-Za-z0-9_.-])")
# upstream explicitMentionRegex (:121-124): "at sign X", "at the rate X",
# "tag X", "mention X"; continuation tokens must be Capitalized
_SPOKEN_MENTION_RE = re.compile(
    r"(?<![\w@])(?i:(?:at\s+(?:sign|the\s+rate)|tag|mention))\s+"
    r"([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,2})"
    r"(?![A-Za-z0-9_.-])")

# upstream hasSpokenSlashCommandContext punctuation set (:310-313)
_SPOKEN_SLASH_BREAK_CHARS = ".!?:;([{"


def _has_spoken_slash_context(text: str, start: int) -> bool:
    """Upstream :305-322 - a spoken "slash fix" squeezes only at the start
    of the text, after sentence punctuation, or after a lead-in verb."""
    prefix = text[:start].strip()
    if not prefix:
        return True
    if prefix[-1] in _SPOKEN_SLASH_BREAK_CHARS:
        return True
    words = re.split(r"[^A-Za-z0-9_-]+", prefix)
    last = words[-1] if words else ""
    return last.lower() in SLASH_SPOKEN_LEAD_IN_WORDS


def squeeze_slash_commands(text: str) -> str:
    """`"/ fix the deploy"` -> `"/fix the deploy"` (token lowercased).

    A `/` not preceded by a word character, followed by one-or-more
    whitespace (upstream ``\\s+``, not a single space) and a 2-40 char
    letter-first ``[A-Za-z0-9_-]`` token, joins to the token — unless the
    lowercased token is in SLASH_REJECTED_TOKENS (upstream
    isValidSlashCommandToken :289-297), which skips the whole match.
    """
    if "/" not in text:  # upstream early-out (:173-175)
        return text

    def _replace(m: re.Match[str]) -> str:
        token = m.group(1)
        if token.lower() in SLASH_REJECTED_TOKENS:
            return m.group(0)  # skip (whole match unchanged)
        return "/" + token.lower()  # upstream :283

    return _SLASH_RE.sub(_replace, text)


def squeeze_spoken_slash_commands(text: str) -> str:
    """`"run slash fix"` -> `"run /fix"` (token lowercased).

    Upstream slashCommandSpokenRegex + context gate: "slash"/"forward slash"
    before a valid command token squeezes to ``/token`` only when the match
    sits at the text start, after sentence punctuation, or after a
    SLASH_SPOKEN_LEAD_IN_WORDS verb (:305-322). Rejected tokens skip.
    """
    if not re.search(r"slash", text, re.IGNORECASE):
        return text
    out: list[str] = []
    pos = 0
    for m in _SPOKEN_SLASH_RE.finditer(text):
        token = m.group(1)
        if token.lower() in SLASH_REJECTED_TOKENS:
            continue
        if not _has_spoken_slash_context(text, m.start()):
            continue
        out.append(text[pos:m.start()])
        out.append("/" + token.lower())
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def squeeze_mentions(text: str) -> str:
    """`"@ John Smith"` -> `"@John Smith"` (first space only; internal
    spacing of multi-token names preserved).

    A literal `@` not preceded by a word character or another `@`, followed
    by whitespace and a 1-3 token name, joins to the name — unless the next
    char after the match is `'`/`’` (possessive guard, upstream :374-380,
    checked against the original text) or any name token is in
    MENTION_REJECTED_TOKENS (upstream isValidMentionName :349-371; any
    rejected token skips the whole match).
    """
    if "@" not in text:
        return text
    out: list[str] = []
    pos = 0
    for m in _MENTION_RE.finditer(text):
        end = m.end()
        if end < len(text) and text[end] in ("'", "\u2019"):
            continue  # possessive guard
        name = m.group(1)
        tokens = [t for t in name.split() if t]
        if not tokens or len(tokens) > 3:
            continue
        if any(t.lower() in MENTION_REJECTED_TOKENS for t in tokens):
            continue  # skip whole match (upstream name guard)
        out.append(text[pos:m.start()])
        out.append("@" + name)  # internal spacing preserved (upstream :343)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def squeeze_spoken_mentions(text: str) -> str:
    """`"at sign John Smith"` -> `"@John Smith"`, `"tag Ana"` -> `"@Ana"`.

    Upstream explicitMentionRegex + name validation: "at sign", "at the
    rate", "tag", or "mention" before a 1-3 token name (continuation tokens
    Capitalized) becomes ``@Name`` with internal spacing preserved. The
    possessive guard and the rejected-token skip mirror the literal pass.
    """
    lowered = text.lower()
    if not ("at " in lowered or "tag " in lowered or "mention " in lowered):
        return text  # upstream early-out (:209-213)
    out: list[str] = []
    pos = 0
    for m in _SPOKEN_MENTION_RE.finditer(text):
        end = m.end()
        if end < len(text) and text[end] in ("'", "\u2019"):
            continue  # possessive guard
        name = m.group(1).strip()
        tokens = [t for t in name.split() if t]
        if not tokens or len(tokens) > 3:
            continue
        if any(t.lower() in MENTION_REJECTED_TOKENS for t in tokens):
            continue
        out.append(text[pos:m.start()])
        out.append("@" + name)  # internal spacing preserved (upstream :343)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def squeeze_slash_mentions(text: str, cfg: dict | None = None) -> str:
    """Literal slash, spoken slash, literal @, spoken mention (upstream
    order :153-167 + :185-196, with the port's literal-@ pass alongside).

    No-op when ``processing.slash_mention_squeeze`` is false (the port's
    default is true; upstream literalDictationFormattingEnabled defaults
    false — documented divergence, SettingsStore.swift:4124-4126).
    """
    if cfg is not None and not cfg.get("processing", {}).get(
            "slash_mention_squeeze", True):
        return text
    text = squeeze_slash_commands(text)
    text = squeeze_spoken_slash_commands(text)
    text = squeeze_mentions(text)
    return squeeze_spoken_mentions(text)
