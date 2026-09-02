"""Per-app prompt sets (upstream per-app prompts) - matching + pipeline."""
from __future__ import annotations

import copy

import pytest

from fluidvoice.config import DEFAULTS
from fluidvoice.processing.per_app import match_app_prompt, system_prompt_for

RULES = [
    {"apps": ["zed", "Code"], "instructions": "Bullet style, no greetings."},
    {"apps": ["firefox"], "instructions": "Casual tone."},
]


@pytest.fixture()
def cfg():
    return copy.deepcopy(DEFAULTS)


class TestMatchAppPrompt:
    def test_matches_case_insensitive_substring(self):
        assert match_app_prompt(RULES, "dev.zed.Zed") == "Bullet style, no greetings."
        assert match_app_prompt(RULES, "code-oss") == "Bullet style, no greetings."

    def test_first_match_wins(self):
        both = RULES + [{"apps": ["zed"], "instructions": "second"}]
        assert match_app_prompt(both, "Zed") == "Bullet style, no greetings."

    def test_star_matches_everything(self):
        rules = [{"apps": ["*"], "instructions": "always"}]
        assert match_app_prompt(rules, "anything.here") == "always"

    def test_no_match_or_no_hint(self):
        assert match_app_prompt(RULES, "org.gnome.TextEditor") is None
        assert match_app_prompt(RULES, None) is None
        assert match_app_prompt([], "zed") is None

    def test_malformed_rules_skipped(self):
        assert match_app_prompt(["oops", {"apps": [], "instructions": "x"}],
                                "zed") is None

    def test_system_prompt_appends_section(self):
        base = "BASE PROMPT"
        out = system_prompt_for(base, "extra rules here")
        assert out.startswith("BASE PROMPT")
        assert "App-specific instructions" in out and "extra rules here" in out
        assert system_prompt_for(base, None) == base


class TestPipelineUsesPerApp:
    def _polish_with_stub_client(self, cfg, app_hint):
        import fluidvoice.daemon as dm
        from tests.test_daemon import StubBackend
        seen = {}

        class StubAIClient:
            def polish(self, text, system_prompt=None):
                seen["prompt"] = system_prompt
                return "polished"

        cfg["ai"]["enabled"] = True
        pipeline = dm.DictationPipeline(cfg, StubBackend("raw"))
        original = dm.AIClient
        dm.AIClient = lambda c: StubAIClient()
        try:
            text, ai_used = pipeline._polish("hello", app_hint=app_hint)
        finally:
            dm.AIClient = original
        return text, ai_used, seen["prompt"]

    def test_matched_app_gets_instructions(self, cfg):
        cfg["ai"]["per_app_prompts"] = RULES
        text, ai_used, prompt = self._polish_with_stub_client(cfg, "dev.zed.Zed")
        assert ai_used and text == "polished"
        assert prompt is not None
        assert "Bullet style, no greetings." in prompt
        assert prompt.startswith("You are a voice-to-text")

    def test_unmatched_app_gets_plain_prompt(self, cfg):
        cfg["ai"]["per_app_prompts"] = RULES
        _text, _ai, prompt = self._polish_with_stub_client(cfg, "org.gnome.Editor")
        assert prompt is None  # plain call, no override


