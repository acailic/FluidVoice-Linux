"""Spoken punctuation engine - a port of FluidVoice's "literal" command system.

Spoken commands are gated behind a prefix word (default "literal"):

    "buy milk literal comma then eggs"   -> "buy milk, then eggs"
    "example literal dot com"            -> "example.com"
    "literal open paren test literal close paren" -> "(test)"
    "hello literal new line world"       -> "hello\\nworld"

Fidelity notes (verified against upstream sources 2026-09):
- Upstream's LIVE rule table (UserDefaults defaults applied via
  makeRules(from:), ASRService+SpokenPunctuationFormatting.swift:141) applies
  every rule UNCONDITIONALLY - the dot/slash/at-sign "context gates" exist
  only in a parameterless makeRules() overload that is never called (dead
  code). This port matches the live behavior: rules are ungated.
- Alias set, spacing semantics and cleanup passes mirror the live table.
- Candidates are matched longest-alias-first (upstream groups by word count
  descending), so "dot dot dot" wins over "dot".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Rule tables (ported from FluidVoice SettingsStore defaults, 4191-4244)
# ---------------------------------------------------------------------------

RIGHT, LEFT, NOSPACE, SPACE = "rightAttached", "leftAttached", "noSpaceAround", "spaceAround"

# (aliases, symbol, spacing)
PUNCTUATION_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("comma",), ",", RIGHT),
    (("period", "full stop"), ".", RIGHT),
    (("dot",), ".", NOSPACE),
    (("question mark", "questionmark"), "?", RIGHT),
    (("exclamation mark", "exclamation point", "bang"), "!", RIGHT),
    (("colon",), ":", RIGHT),
    (("semicolon", "semi colon"), ";", RIGHT),
    (("ellipsis", "dot dot dot", "three dots"), "...", RIGHT),
    (("slash", "forward slash", "forwardslash"), "/", NOSPACE),
    (("backslash", "back slash"), "\\", NOSPACE),
    (("hyphen",), "-", NOSPACE),
    (("dash", "minus sign"), "-", SPACE),
    (("em dash", "long dash"), "—", SPACE),
    (("en dash",), "–", SPACE),
    (("open parenthesis", "open parentheses", "open paren", "left parenthesis",
      "left parentheses", "left paren"), "(", LEFT),
    (("close parenthesis", "close parentheses", "close paren", "right parenthesis",
      "right parentheses", "right paren"), ")", RIGHT),
    (("open bracket", "open square bracket", "left bracket", "left square bracket"), "[", LEFT),
    (("close bracket", "close square bracket", "right bracket", "right square bracket"), "]", RIGHT),
    (("open brace", "open curly brace", "open curly bracket", "left brace",
      "left curly brace", "left curly bracket"), "{", LEFT),
    (("close brace", "close curly brace", "close curly bracket", "right brace",
      "right curly brace", "right curly bracket"), "}", RIGHT),
    (("open angle bracket", "left angle bracket", "less than sign"), "<", LEFT),
    (("close angle bracket", "right angle bracket", "greater than sign"), ">", RIGHT),
    (("double quote", "quote", "quotes", "quotation mark"), '"', "toggleDoubleQuote"),
    (("open quote", "opening quote", "open double quote"), '"', LEFT),
    (("close quote", "closing quote", "close double quote"), '"', RIGHT),
    (("single quote",), "'", "toggleSingleQuote"),
    (("apostrophe",), "'", NOSPACE),
    (("at the rate", "at sign", "commercial at"), "@", NOSPACE),
    (("ampersand", "and sign"), "&", SPACE),
    (("plus sign", "plus"), "+", SPACE),
    (("equals sign", "equal sign", "equal", "equals"), "=", SPACE),
    (("percent sign", "percentage sign", "percent"), "%", RIGHT),
    (("dollar sign", "dollar"), "$", LEFT),
    (("hash", "hash sign", "hashtag", "pound sign", "number sign"), "#", NOSPACE),
    (("asterisk", "star symbol"), "*", NOSPACE),
    (("underscore",), "_", NOSPACE),
    (("pipe", "vertical bar"), "|", NOSPACE),
    (("tilde",), "~", NOSPACE),
    (("caret",), "^", NOSPACE),
    (("backtick", "back tick"), "`", NOSPACE),
]

# (aliases, rendered, strip_trailing_hspace)
FORMATTING_ACTIONS: list[tuple[tuple[str, ...], str, bool]] = [
    (("new line", "next line"), "\n", True),
    (("new paragraph", "next paragraph"), "\n\n", True),
    (("tab",), "\t", True),
    (("space",), " ", True),
]

# Flat longest-alias-first candidate lists (upstream groups by word count
# descending) - every alias participates in the ordering, so "dot dot dot"
# beats "dot" regardless of rule order.
_ORDERED_ACTIONS: list[tuple[list[str], str, bool]] = sorted(
    ((alias.split(), rendered, strip_hws)
     for aliases, rendered, strip_hws in FORMATTING_ACTIONS for alias in aliases),
    key=lambda c: len(c[0]), reverse=True)

# User-extensible spoken formatting actions (upstream
# SpokenFormattingActionRule, SettingsStore.swift:4170-4187): extra trigger
# aliases per action, on top of the built-in defaults above.
_ACTION_RENDERED = {"new_line": "\n", "new_paragraph": "\n\n",
                    "tab": "\t", "space": " "}


def _ordered_actions(extra: dict[str, list[str]] | None
                     ) -> list[tuple[list[str], str, bool]]:
    """Built-in action aliases plus validated user extras, longest-first.

    Unknown action names, non-list alias values and non-string/blank
    aliases are ignored - the built-in table always stays available."""
    if not extra:
        return _ORDERED_ACTIONS
    cands = list(_ORDERED_ACTIONS)
    for action, aliases in extra.items():
        rendered = _ACTION_RENDERED.get(str(action))
        if rendered is None or not isinstance(aliases, (list, tuple)):
            continue
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                cands.append((alias.lower().split(), rendered, True))
    cands.sort(key=lambda c: len(c[0]), reverse=True)
    return cands

_ORDERED_PUNCT: list[tuple[list[str], str, str]] = sorted(
    ((alias.split(), symbol, spacing)
     for aliases, symbol, spacing in PUNCTUATION_RULES for alias in aliases),
    key=lambda c: len(c[0]), reverse=True)

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TOKEN_RE = re.compile(r"[^\W_]+|\W+", re.UNICODE)
_HWS = " \t"

# Symbols for the comma-sandwich cleanup (upstream punctuationPairCommaCleanup
# - comma itself excluded: a comma must sit BETWEEN two of these to be dropped).
COMMA_PAIR_SYMBOLS = set("+=%—–/\\@#$&*_|~^<>()[]{}\"'`.?!:;")


@dataclass
class _Out:
    """Output buffer that remembers which characters the engine generated."""
    chars: list[str] = field(default_factory=list)
    generated: list[bool] = field(default_factory=list)

    def append(self, text: str, generated: bool = False) -> None:
        self.chars.extend(text)
        self.generated.extend([generated] * len(text))

    def strip_trailing_hws(self) -> None:
        while self.chars and self.chars[-1] in _HWS:
            self.chars.pop()
            self.generated.pop()

    def text(self) -> str:
        return "".join(self.chars)


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _is_hws(token: str) -> bool:
    return token != "" and all(c in _HWS for c in token)


def _is_word(token: str) -> bool:
    return bool(WORD_RE.fullmatch(token)) if token else False


def _match_words(tokens: list[str], start: int, words: list[str]) -> int | None:
    """Match `words` starting at token index `start`, allowing only pure
    horizontal whitespace *between* them. Returns the index right after the
    last matched word (trailing whitespace is left in the stream) or None."""
    i = start
    last_end: int | None = None
    for w in words:
        if i >= len(tokens) or tokens[i].lower() != w or not _is_word(tokens[i]):
            return None
        i += 1
        last_end = i
        while i < len(tokens) and _is_hws(tokens[i]):
            i += 1
    return last_end


class _Renderer:
    _pending_skip_hws: bool = False

    def __init__(self):
        self.out = _Out()
        self.quote_state: dict[str, bool] = {}  # True -> next is closing

    def emit_normal(self, text: str) -> None:
        if text:
            self.out.append(text, generated=False)

    def skip_following_hws(self, tokens: list[str], i: int) -> int:
        while i < len(tokens) and _is_hws(tokens[i]):
            i += 1
        return i

    def render(self, symbol: str, spacing: str, tokens: list[str], i: int) -> int:
        """Render a symbol; `i` is the token index right after the alias."""
        if spacing == "toggleDoubleQuote":
            closing = self.quote_state.get('"', False)
            spacing = RIGHT if closing else LEFT
            self.quote_state['"'] = not closing
        elif spacing == "toggleSingleQuote":
            closing = self.quote_state.get("'", False)
            spacing = RIGHT if closing else LEFT
            self.quote_state["'"] = not closing
        if spacing in (RIGHT, NOSPACE):
            self.out.strip_trailing_hws()
        elif spacing == SPACE:
            self.out.strip_trailing_hws()
            if self.out.chars and self.out.chars[-1] not in "\n":
                self.out.append(" ")
        self.out.append(symbol, generated=True)
        if spacing in (LEFT, NOSPACE):
            self._pending_skip_hws = True
            return self.skip_following_hws(tokens, i)
        if spacing == SPACE:
            # upstream: skip following whitespace, then add a trailing space
            # when any non-whitespace part follows
            i = self.skip_following_hws(tokens, i)
            if any(not _is_hws(t) for t in tokens[i:]):
                self.out.append(" ")
            return i
        return i

    def flush_skip(self, tokens: list[str], i: int) -> int:
        if self._pending_skip_hws:
            self._pending_skip_hws = False
            i = self.skip_following_hws(tokens, i)
        return i


def _cleanup_generated(out: _Out) -> str:
    """Upstream cleanup passes:
    A) a generated comma sandwiched between two symbols is dropped, and a
       generated comma before a generated % preceded by an ASCII digit;
    B) one trailing '.' stripped from ORIGINAL text before a formatting
       action; a leading '.' (always) or ',' (newline actions only) stripped
       from ORIGINAL text right after a formatting action.
    """
    chars, gen = out.chars, out.generated

    def next_idx(idx: int) -> int | None:
        j = idx + 1
        while j < len(chars) and chars[j] in _HWS:
            j += 1
        return j if j < len(chars) else None

    def prev_idx(idx: int) -> int | None:
        j = idx - 1
        while j >= 0 and chars[j] in _HWS:
            j -= 1
        return j if j >= 0 else None

    drop: set[int] = set()
    # Pass A - generated comma noise
    for idx, c in enumerate(chars):
        if not gen[idx] or c != ",":
            continue
        nxt, prv = next_idx(idx), prev_idx(idx)
        if nxt is not None and prv is not None:
            if gen[nxt] and chars[nxt] in COMMA_PAIR_SYMBOLS \
                    and (chars[prv] in COMMA_PAIR_SYMBOLS or gen[prv]):
                drop.add(idx)
                continue
        if nxt is not None and gen[nxt] and chars[nxt] == "%" \
                and prv is not None and chars[prv].isdigit():
            drop.add(idx)
    # Pass B - sentence punctuation beside formatting actions (original text)
    for idx, c in enumerate(chars):
        if gen[idx]:
            continue
        if c == ".":  # trailing period of original text before an action
            nxt = next_idx(idx)
            if nxt is not None and gen[nxt] and chars[nxt] in "\n\t":
                drop.add(idx)
        if c in ".,":
            prv = prev_idx(idx)
            if prv is not None and gen[prv] and chars[prv] in "\n\n\t":
                if c == "." or chars[prv] == "\n":
                    drop.add(idx)
    kept = [c for i, c in enumerate(chars) if i not in drop]
    return "".join(kept)


def format_spoken_punctuation(text: str, *, prefix: str = "literal",
                              enabled: bool = True, app_hint: str | None = None,
                              extra_actions: dict[str, list[str]] | None = None) -> str:
    if not enabled or not text or not prefix:
        return text
    if prefix.lower() not in text.lower():  # fast gate: full prefix substring
        return text

    tokens = _tokenize(text)
    prefix_words = prefix.lower().split()
    ordered_actions = _ordered_actions(extra_actions)
    r = _Renderer()
    i = 0
    while i < len(tokens):
        i = r.flush_skip(tokens, i)
        if i >= len(tokens):
            break
        after_prefix = _match_words(tokens, i, prefix_words) if _is_word(tokens[i]) else None
        if after_prefix is None:
            r.emit_normal(tokens[i])
            i += 1
            continue
        j = r.skip_following_hws(tokens, after_prefix)
        matched = False
        for words, rendered, strip_hws in ordered_actions:
            end = _match_words(tokens, j, words)
            if end is not None:
                if strip_hws:
                    r.out.strip_trailing_hws()
                r.out.append(rendered, generated=True)
                r._pending_skip_hws = True
                i = r.flush_skip(tokens, end)
                matched = True
                break
        if not matched:
            for words, symbol, spacing in _ORDERED_PUNCT:
                end = _match_words(tokens, j, words)
                if end is not None:
                    i = r.render(symbol, spacing, tokens, end)
                    matched = True
                    break
        if matched:
            continue
        # prefix matched but no rule followed: emit the prefix words verbatim
        for k in range(i, after_prefix):
            r.emit_normal(tokens[k])
        i = after_prefix

    return _cleanup_generated(r.out)
