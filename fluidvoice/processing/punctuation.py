"""Spoken punctuation engine - a port of FluidVoice's "literal" command system.

Spoken commands are gated behind a prefix word (default "literal"):

    "buy milk literal comma then eggs"   -> "buy milk, then eggs"
    "example literal dot com"            -> "example.com"
    "literal open paren test literal close paren" -> "(test)"
    "hello literal new line world"       -> "hello\\nworld"

Matching mirrors upstream: the text is tokenized into alphanumeric runs and
"other" runs; a command fires when the prefix word is followed (across pure
horizontal whitespace) by a phrase alias, word by word. Symbols are rendered
with the same spacing semantics (rightAttached / leftAttached / noSpaceAround
/ spaceAround / toggling quotes), and the same generated-punctuation cleanup
passes run afterwards.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Rule tables (ported from FluidVoice SettingsStore defaults)
# ---------------------------------------------------------------------------

RIGHT, LEFT, NOSPACE, SPACE = "rightAttached", "leftAttached", "noSpaceAround", "spaceAround"

# (aliases, symbol, spacing)
PUNCTUATION_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("comma",), ",", RIGHT),
    (("period", "full stop"), ".", RIGHT),
    (("dot",), ".", NOSPACE),  # requires dot-context, see below
    (("question mark", "questionmark"), "?", RIGHT),
    (("exclamation mark", "exclamation point", "bang"), "!", RIGHT),
    (("colon",), ":", RIGHT),
    (("semicolon", "semi colon"), ";", RIGHT),
    (("ellipsis", "dot dot dot", "three dots"), "...", RIGHT),
    (("slash", "forward slash", "forwardslash"), "/", NOSPACE),  # requires path-context
    (("backslash", "back slash"), "\\", NOSPACE),
    (("hyphen",), "-", NOSPACE),
    (("dash", "minus sign"), "-", SPACE),
    (("em dash", "long dash"), "—", SPACE),
    (("en dash",), "–", SPACE),
    (("open parenthesis", "open paren", "left parenthesis", "left paren", "open parentheses"), "(", LEFT),
    (("close parenthesis", "close paren", "right parenthesis", "right paren", "close parentheses"), ")", RIGHT),
    (("open bracket", "open square bracket", "left bracket", "left square bracket"), "[", LEFT),
    (("close bracket", "close square bracket", "right bracket", "right square bracket"), "]", RIGHT),
    (("open brace", "open curly brace", "open curly bracket", "left brace", "left curly brace"), "{", LEFT),
    (("close brace", "close curly brace", "close curly bracket", "right brace"), "}", RIGHT),
    (("open angle bracket", "open angled bracket", "less than sign"), "<", LEFT),
    (("close angle bracket", "close angled bracket", "greater than sign"), ">", RIGHT),
    (("double quote", "open quote", "opening quote", "open double quote"), '"', LEFT),
    (("close quote", "closing quote", "close double quote"), '"', RIGHT),
    (("quote", "quotes", "quotation mark"), '"', "toggleDoubleQuote"),
    (("single quote",), "'", "toggleSingleQuote"),
    (("apostrophe",), "'", NOSPACE),
    (("at the rate",), "@", NOSPACE),  # always active
    (("at sign", "commercial at"), "@", NOSPACE),  # only in "at-sign apps"
    (("ampersand", "and sign"), "&", SPACE),
    (("plus sign",), "+", SPACE),
    (("equals sign", "equal sign"), "=", SPACE),
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

# Contexts
PATH_CHARS = set("./\\:@_~")
DOT_TLD_WORDS = {"com", "net", "org", "io", "ai", "dev", "www", "http", "https", "app", "co"}
DOT_REJECT_AFTER = {"a", "an", "my", "our", "that", "the", "their", "this", "your"}
SLASH_PATH_WORDS = {"api", "bin", "home", "usr", "var", "documents", "desktop",
                    "http", "https", "www"}
ATSIGN_APPS = {"codex", "chatgpt", "claude", "cursor", "windsurf", "xcode",
               "visualstudiocode", "vscode", "code", "terminal", "iterm", "warp",
               "ghostty", "kitty", "alacritty", "slack", "discord", "teams"}

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TOKEN_RE = re.compile(r"[^\W_]+|\W+", re.UNICODE)
_HWS = " \t"


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

    def ends_with_hws(self) -> bool:
        return bool(self.chars) and self.chars[-1] in _HWS

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


def _next_word_token(tokens: list[str], start: int) -> str | None:
    """First alphanumeric token at or after `start` (used for context checks)."""
    for t in tokens[start:]:
        if _is_word(t):
            return t.lower()
        if t.strip() == "":
            continue
        # any punctuation stops the context scan
        return None
    return None


def _prev_word_token(tokens: list[str], end: int) -> str | None:
    for t in reversed(tokens[:end]):
        if _is_word(t):
            return t.lower()
        if t.strip() == "":
            continue
        return None
    return None


def _looks_path_like(word: str) -> bool:
    if not word:
        return False
    return any(c in PATH_CHARS for c in word) or word.isdigit() or len(word) <= 3


def _dot_context(prev_word: str | None, next_word: str | None) -> bool:
    if prev_word in DOT_REJECT_AFTER:
        return False
    for w in (prev_word, next_word):
        if w and (any(c in PATH_CHARS for c in w) or w in DOT_TLD_WORDS
                  or w.isdigit() or len(w) <= 3):
            return True
    return False


def _slash_context(prev_word: str | None, next_word: str | None) -> bool:
    for w in (prev_word, next_word):
        if w and (any(c in PATH_CHARS for c in w) or w in SLASH_PATH_WORDS or w.isdigit()):
            return True
    return False


def _atsign_app(app_hint: str | None) -> bool:
    if not app_hint:
        return False
    hint = re.sub(r"[^a-z0-9]", "", app_hint.lower())
    return any(app in hint or hint in app for app in ATSIGN_APPS)


class _Renderer:
    def __init__(self, app_hint: str | None):
        self.app_hint = app_hint
        self.out = _Out()
        self.quote_state: dict[str, bool] = {}  # True -> next is closing

    def emit_normal(self, text: str) -> None:
        if text:
            self.out.append(text, generated=False)

    def skip_following_hws(self, tokens: list[str], i: int) -> int:
        while i < len(tokens) and _is_hws(tokens[i]):
            i += 1
        return i

    def render(self, symbol: str, spacing: str) -> None:
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

    _pending_skip_hws: bool = False

    def flush_skip(self, tokens: list[str], i: int) -> int:
        if self._pending_skip_hws:
            self._pending_skip_hws = False
            i = self.skip_following_hws(tokens, i)
        return i


def _cleanup_generated(out: _Out) -> str:
    """Ported cleanup passes over generated characters only."""
    chars, gen = out.chars, out.generated
    drop: set[int] = set()
    sentence_punct = {".", ","}
    other_punct = set(".,!?;:…%")

    for idx in range(len(chars)):
        if not gen[idx]:
            continue
        c = chars[idx]
        # 1) generated comma adjacent to other generated punctuation -> drop comma
        if c == ",":
            nxt = idx + 1
            while nxt < len(chars) and chars[nxt] in _HWS:
                nxt += 1
            if nxt < len(chars) and gen[nxt] and chars[nxt] in other_punct and chars[nxt] != ",":
                drop.add(idx)
        # 2) generated sentence punctuation beside formatting actions
        if c in sentence_punct:
            nxt = idx + 1
            while nxt < len(chars) and chars[nxt] in _HWS:
                nxt += 1
            if nxt < len(chars) and gen[nxt] and chars[nxt] in "\n\t":
                drop.add(idx)
    kept = [c for i, c in enumerate(chars) if i not in drop]
    text = "".join(kept)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def format_spoken_punctuation(text: str, *, prefix: str = "literal",
                              enabled: bool = True, app_hint: str | None = None) -> str:
    if not enabled or not text or not prefix:
        return text
    prefix_words = prefix.lower().split()
    if prefix_words and prefix_words[-1] not in text.lower():
        return text  # fast gate: no prefix word anywhere

    tokens = _tokenize(text)
    r = _Renderer(app_hint)
    i = 0
    while i < len(tokens):
        i = r.flush_skip(tokens, i) if r._pending_skip_hws else i
        if i >= len(tokens):
            break
        # try to match the prefix at i
        after_prefix = _match_words(tokens, i, prefix_words) if _is_word(tokens[i]) else None
        if after_prefix is None:
            r.emit_normal(tokens[i])
            i += 1
            continue
        prev_word = _prev_word_token(tokens, i)
        j = r.skip_following_hws(tokens, after_prefix)  # allow ws before the phrase
        matched = False
        # formatting actions first (they shadow punctuation aliases)
        for aliases, rendered, strip_hws in FORMATTING_ACTIONS:
            for alias in aliases:
                end = _match_words(tokens, j, alias.split())
                if end is not None:
                    if strip_hws:
                        r.out.strip_trailing_hws()
                    r.out.append(rendered, generated=True)
                    r._pending_skip_hws = True
                    i = r.flush_skip(tokens, end)
                    matched = True
                    break
            if matched:
                break
        if matched:
            continue
        for aliases, symbol, spacing in PUNCTUATION_RULES:
            for alias in aliases:
                end = _match_words(tokens, j, alias.split())
                if end is None:
                    continue
                next_word = _next_word_token(tokens, end)
                if alias == "dot" and not _dot_context(prev_word, next_word):
                    continue  # keep the spoken word "dot" literal
                if alias in ("slash", "forward slash", "forwardslash") and \
                        not _slash_context(prev_word, next_word):
                    continue
                if alias in ("at sign", "commercial at") and not _atsign_app(app_hint):
                    continue
                r.render(symbol, spacing)
                i = r.flush_skip(tokens, end)
                matched = True
                break
            if matched:
                break
        if matched:
            continue
        # prefix matched but no rule followed: emit the prefix words verbatim
        for k in range(i, after_prefix):
            r.emit_normal(tokens[k])
        i = after_prefix

    return _cleanup_generated(r.out)
