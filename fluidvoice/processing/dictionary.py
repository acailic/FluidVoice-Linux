"""Custom dictionary replacements (case-insensitive, word-boundary, longest first)."""
from __future__ import annotations

import re


def _pattern(trigger: str) -> re.Pattern:
    escaped = re.escape(trigger.strip())
    return re.compile(r"(?<!\w)" + escaped + r"(?!\w)", re.IGNORECASE)


def apply_custom_dictionary(text: str, entries: list[dict]) -> str:
    if not entries:
        return text
    rules: list[tuple[str, re.Pattern, str]] = []
    for entry in entries:
        replacement = entry.get("replacement", "")
        for trigger in entry.get("triggers", []):
            t = trigger.strip()
            if t:
                rules.append((t, _pattern(t), replacement))
    # Longest trigger first so "fluid voice" wins over "fluid".
    rules.sort(key=lambda r: len(r[0]), reverse=True)
    for _, pattern, replacement in rules:
        text = pattern.sub(replacement.replace("\\", "\\\\"), text)
    return text
