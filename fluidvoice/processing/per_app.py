"""Per-app prompt sets (upstream "per-app prompts"): extra AI-polish
instructions applied automatically when dictating into a matching app.

Rules live in ai.per_app_prompts as [{"apps": ["zed", "firefox"],
"instructions": "..."}]. The first rule whose pattern matches the active
window class (case-insensitive substring, "*" matches everything) wins.
"""
from __future__ import annotations


def match_app_prompt(rules: list, app_hint: str | None) -> str | None:
    """Instructions for this app, or None. Pure and testable."""
    if not app_hint or not rules:
        return None
    app = app_hint.lower()
    for rule in rules:
        try:
            patterns = [str(p).lower().strip() for p in rule.get("apps", [])]
            instructions = str(rule.get("instructions", "")).strip()
        except AttributeError:
            continue  # malformed rule (not a dict)
        if not instructions or not patterns:
            continue
        if "*" in patterns or any(p and p in app for p in patterns):
            return instructions
    return None


def system_prompt_for(base_prompt: str, instructions: str | None) -> str:
    """Base dictation prompt + the app-specific section, upstream style."""
    if not instructions:
        return base_prompt
    return (f"{base_prompt}\n\n"
            "## App-specific instructions (applies to this dictation):\n"
            f"{instructions}")
