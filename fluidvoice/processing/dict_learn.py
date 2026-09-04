"""Dictionary auto-learning from post-insertion corrections (suggest-only).

Signal: history entries keep ``edited_from`` — the text as originally
dictated, written by :func:`fluidvoice.history.update_text` on the entry's
first user edit (first edit wins; later edits overwrite ``text`` only).
Diffing ``edited_from`` against the final ``text`` yields (heard, corrected)
pairs; a pair seen in >= MIN_OCCURRENCES entries becomes a *suggestion* in
Settings → Dictation. Nothing is ever auto-added silently.

Upstream semantics kept (Fluid 1.6.3 "Auto-suggested custom-dictionary
replacements", AutomaticDictionaryCorrectionTracker.swift): threshold of 2
occurrences; <= 3 words per side; <= 40 chars per side / <= 70 combined;
>= 2 letters per side; pairs whose trigger is already a dictionary trigger
are suppressed; punctuation/numeric/filler spans rejected.

Deliberate divergences (docs/STATUS.md §"Intentional divergences"):
- case-only corrections ARE candidates ("miro board" → "Miro board" is the
  canonical dictionary use; upstream rejects them);
- surfaced as a passive Settings list, not a 5 s overlay, so no cooldowns;
- dismissal is permanent (upstream resurfaces after 7 days, max 3×);
- no config toggle — the list only records what the user already typed
  (history.save = false disables the signal at the source).

Noise rule (the plan's "identical after case-fold + non-letter strip"),
made precise: a replace span whose tokens are raw-identical after edge
punctuation trimming is a pure punctuation/spacing rewrite and is dropped
(e.g. "Miro," → "Miro"). Whitespace-only rewrites ("miro  board" →
"miro board") produce no opcode at all — str.split() collapses runs.
Word merges ("gnu plot" → "gnuplot") carry a dictionary lesson and pass.

An entry is one correction event: when a diff yields several *different*
qualifying pairs the edit rewrote multiple parts of the sentence — that is
editing, not correcting (upstream sees one focused field edit per window)
— so the entry yields nothing. The same pair repeated within one entry
(difflib splits it into adjacent ops) collapses to one candidate.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from pathlib import Path

from .. import paths
from ..config import DEFAULT_FILLERS

MIN_OCCURRENCES = 2  # upstream DictionarySuggestionPolicyConfig.requiredOccurrences

# a word: Unicode letters, internal apostrophe/hyphen allowed
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")


def _trim_punct(token: str) -> str:
    """Strip edge Unicode punctuation (same rule as processing/fillers.py)."""
    start, end = 0, len(token)
    while start < end and unicodedata.category(token[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(token[end - 1]).startswith("P"):
        end -= 1
    return token[start:end]


def _is_word(token: str) -> bool:
    return bool(_WORD_RE.fullmatch(token))


def extract_candidates(edited_from: str, text: str,
                       fillers: list[str] | None = None) -> list[tuple[str, str]]:
    """(heard, corrected) pairs suggested by one history edit, at most one
    distinct pair per call (see module docstring). Pure function."""
    if edited_from is None or text is None or edited_from == text:
        return []
    filler_set = ({f.strip().lower() for f in (fillers if fillers is not None
                                               else DEFAULT_FILLERS)
                   if f and f.strip()})
    old_tokens = str(edited_from).split()
    new_tokens = str(text).split()
    sm = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    pairs: list[tuple[str, str]] = []
    for _tag, i1, i2, j1, j2 in sm.get_opcodes():
        if _tag != "replace":
            continue
        # an op rewriting > 3 tokens on either side is editing, not correcting
        if not (1 <= i2 - i1 <= 3 and 1 <= j2 - j1 <= 3):
            continue
        old_span = [_trim_punct(t) for t in old_tokens[i1:i2]]
        new_span = [_trim_punct(t) for t in new_tokens[j1:j2]]
        if not all(_is_word(t) for t in old_span + new_span):
            continue  # punctuation/numeric/empty span
        if any(t.lower() in filler_set for t in old_span + new_span):
            continue
        heard, corrected = " ".join(old_span), " ".join(new_span)
        if heard == corrected:
            continue  # punctuation/spacing-only rewrite
        if len(heard) < 2 or len(corrected) < 2:
            continue  # upstream: each side >= 2 alphanumeric chars, >= 1 letter
        if heard.lower() == corrected.lower() and heard != corrected:
            # case-only correction: extend one word of context on the right
            # so the trigger covers the phrase being recased (the canonical
            # "miro" → "Miro" fix wants the "miro board" → "Miro board"
            # trigger), staying within the 3-words-per-side limit
            if i2 < len(old_tokens) and j2 < len(new_tokens):
                nxt_old = _trim_punct(old_tokens[i2])
                nxt_new = _trim_punct(new_tokens[j2])
                if (_is_word(nxt_old) and _is_word(nxt_new)
                        and nxt_old.lower() not in filler_set
                        and nxt_new.lower() not in filler_set
                        and len(old_span) < 3 and len(new_span) < 3):
                    heard = heard + " " + nxt_old
                    corrected = corrected + " " + nxt_new
        if len(heard) > 40 or len(corrected) > 40 \
                or len(heard) + len(corrected) > 70:
            continue
        pairs.append((heard, corrected))
    if len(set(pairs)) > 1:
        return []  # scattered rewrite: editing, not correcting
    return list(dict.fromkeys(pairs))


# -- suggestion store (decisions only; counts derive from history) -------------


def _empty_store() -> dict:
    return {"dismissed": [], "accepted": []}


def load_store(path) -> dict:
    """Missing/corrupt file ⇒ empty decisions, never raises."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_store()
    out = _empty_store()
    if isinstance(data, dict):
        for key in ("dismissed", "accepted"):
            vals = data.get(key)
            if isinstance(vals, list):
                out[key] = [[str(p[0]), str(p[1])] for p in vals
                            if isinstance(p, (list, tuple)) and len(p) == 2
                            and all(isinstance(x, str) for x in p)]
    return out


def save_store(path, store: dict) -> None:
    """Atomic write (tmp + replace, mirroring history._atomic_write)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"dismissed": [list(p) for p in store.get("dismissed", [])],
               "accepted": [list(p) for p in store.get("accepted", [])]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def _record_decision(key: str, heard: str, corrected: str, path=None) -> None:
    p = Path(path) if path is not None else paths.dictionary_suggestions_file()
    store = load_store(p)
    if [heard, corrected] not in store[key]:
        store[key].append([heard, corrected])
    save_store(p, store)


def dismiss(heard: str, corrected: str, path=None) -> None:
    """Permanently: pending_suggestions never returns a dismissed pair."""
    _record_decision("dismissed", heard, corrected, path)


def record_accepted(heard: str, corrected: str, path=None) -> None:
    """Accepted pairs are never resuggested either (delete the dictionary
    entry and re-correct twice to see the pair again)."""
    _record_decision("accepted", heard, corrected, path)


# -- pending suggestions -------------------------------------------------------


def pending_suggestions(cfg: dict, entries: list[dict], store: dict | None = None,
                        min_occurrences: int = MIN_OCCURRENCES) -> list[dict]:
    """[{"heard", "corrected", "count"}] sorted by count desc, then the ts
    of the entry that last contained the pair, desc. Counts come from the
    history itself (one entry = one correction event); the store only
    records dismissed/accepted decisions."""
    if store is None:
        store = load_store(paths.dictionary_suggestions_file())
    processing = cfg.get("processing", {}) if isinstance(cfg, dict) else {}
    fillers = processing.get("filler_words")
    known_triggers = {str(t).lower()
                      for entry in processing.get("dictionary") or []
                      for t in (entry.get("triggers") or [])}
    dismissed = {tuple(p) for p in store.get("dismissed", [])}
    accepted = {tuple(p) for p in store.get("accepted", [])}
    counts: dict[tuple[str, str], int] = {}
    last_ts: dict[tuple[str, str], float] = {}
    for entry in entries:
        old = entry.get("edited_from")
        if old is None:
            continue
        for heard, corrected in extract_candidates(str(old),
                                                   str(entry.get("text", "")),
                                                   fillers):
            pair = (heard, corrected)
            if heard.lower() in known_triggers or pair in dismissed \
                    or pair in accepted:
                continue
            counts[pair] = counts.get(pair, 0) + 1
            last_ts[pair] = max(last_ts.get(pair, 0.0),
                                float(entry.get("ts", 0.0)))
    ranked = sorted(counts.items(),
                    key=lambda kv: (-kv[1], -last_ts.get(kv[0], 0.0)))
    return [{"heard": h, "corrected": c, "count": n}
            for (h, c), n in ranked if n >= min_occurrences]


def accept_merge(dictionary: list[dict], heard: str,
                 corrected: str) -> list[dict]:
    """Merge an accepted pair into a custom dictionary without duplicating
    triggers (upstream CustomDictionaryTrainingMerge.mergedEntries,
    simplified). Never mutates the input list."""
    merged = [dict(entry) for entry in dictionary]
    for entry in merged:
        if str(entry.get("replacement", "")).lower() == corrected.lower():
            triggers = [str(t) for t in entry.get("triggers") or []]
            if not any(t.lower() == heard.lower() for t in triggers):
                triggers.append(heard)
            entry["triggers"] = triggers  # keeps the stored replacement text
            return merged
    merged.append({"triggers": [heard], "replacement": corrected})
    return merged
