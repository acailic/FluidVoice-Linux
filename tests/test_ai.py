import pytest

from fluidvoice.ai.client import AIClient, _endpoint, strip_thinking
from fluidvoice.ai.prompts import (
    BASE_DICTATION_PROMPT,
    DEFAULT_DICTATION_PROMPT_BODY,
    default_dictation_prompt,
    render_dictation_user_message,
)


class TestPrompts:
    def test_base_prompt_verbatim_head(self):
        assert BASE_DICTATION_PROMPT.startswith(
            "You are a voice-to-text dictation cleaner.")

    def test_body_contains_self_corrections(self):
        assert "Self-Corrections" in DEFAULT_DICTATION_PROMPT_BODY

    def test_combined_prompt(self):
        combined = default_dictation_prompt()
        assert combined.startswith(BASE_DICTATION_PROMPT)
        assert combined.endswith(DEFAULT_DICTATION_PROMPT_BODY)

    def test_render_transcript_placeholder(self):
        out = render_dictation_user_message("say: ${transcript}", "hello world")
        assert out == "say: hello world"

    def test_render_plain_prompt(self):
        out = render_dictation_user_message("Clean this:", "hello")
        assert out == "Clean this:\n\nhello"

    def test_render_empty_prompt(self):
        assert render_dictation_user_message("", "hello") == "hello"
        assert render_dictation_user_message("   ", "hello") == "hello"


class TestEndpoint:
    def test_appends_path(self):
        assert _endpoint("https://api.openai.com/v1") == \
            "https://api.openai.com/v1/chat/completions"

    def test_respects_existing(self):
        assert _endpoint("http://localhost:11434/v1/chat/completions") == \
            "http://localhost:11434/v1/chat/completions"
        assert _endpoint("http://x/api/chat") == "http://x/api/chat"

    def test_trailing_slash(self):
        assert _endpoint("http://localhost:1234/v1/") == \
            "http://localhost:1234/v1/chat/completions"


class TestStripThinking:
    def test_think_tags(self):
        assert strip_thinking("<think>reasoning</think>answer") == "answer"

    def test_thinking_tags(self):
        assert strip_thinking("<thinking>x</thinking>y") == "y"

    def test_orphan_close(self):
        assert strip_thinking("let me think... </think>final text") == "final text"

    def test_stray_close_tag_is_thinking_boundary(self):
        # upstream semantics: everything before a bare close tag was thinking
        assert strip_thinking("a </think> b") == "b"

    def test_plain_text_untouched(self):
        assert strip_thinking("just text") == "just text"


class TestAIClientDefaults:
    def test_config_from_toml_dict(self):
        cfg = {"ai": {"base_url": "http://localhost:11434/v1", "model": "qwen3:8b",
                      "api_key": "", "api_key_env": "FLUIDVOICE_API_KEY",
                      "temperature": 0.2, "timeout_seconds": 60, "max_retries": 3}}
        client = AIClient(cfg)
        assert client.configured
        assert client.api_key == ""  # no env var set in tests

    def test_not_configured(self):
        cfg = {"ai": {"base_url": "http://localhost:11434/v1", "model": "",
                      "api_key": "", "api_key_env": "NOPE", "temperature": 0.2,
                      "timeout_seconds": 60, "max_retries": 3}}
        assert not AIClient(cfg).configured
