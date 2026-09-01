import pytest

from fluidvoice.ai import client as ai_client
from fluidvoice.ai.client import AIError, AIClient, _endpoint, strip_thinking
import json
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


class TestChatTransport:
    """chat() transport behavior with a mocked urlopen (no network)."""

    def make_client(self, **overrides):
        import copy
        cfg = {"ai": {"base_url": "http://x/v1", "model": "m", "api_key": "",
                      "api_key_env": "NOPE", "temperature": 0.2,
                      "timeout_seconds": 5, "max_retries": 3}}
        cfg["ai"].update(overrides)
        return AIClient(cfg)

    def _respond(self, payload: dict, status: int = 200):
        import io

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        body = json.dumps(payload).encode()
        if status != 200:
            import urllib.error
            err = urllib.error.HTTPError("url", status, "err", {}, io.BytesIO(body))
            raise err
        return Resp(body)

    def test_success(self, monkeypatch):
        client = self.make_client()
        monkeypatch.setattr(ai_client.urllib.request, "urlopen",
                            lambda req, timeout=None: self._respond(
                                {"choices": [{"message": {"content": "hi"}}]}))
        assert client.chat("hello") == "hi"

    def test_retries_then_succeeds(self, monkeypatch):
        attempts = {"n": 0}

        def flaky(req, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 3:
                import urllib.error
                raise urllib.error.URLError("conn reset")
            return self._respond({"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr(ai_client.urllib.request, "urlopen", flaky)
        monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
        assert self.make_client().chat("x") == "ok"
        assert attempts["n"] == 3

    def test_config_error_no_retry(self, monkeypatch):
        attempts = {"n": 0}

        def always_401(req, timeout=None):
            attempts["n"] += 1
            return self._respond({}, status=401)

        monkeypatch.setattr(ai_client.urllib.request, "urlopen", always_401)
        with pytest.raises(AIError, match="401"):
            self.make_client().chat("x")
        assert attempts["n"] == 1  # did not retry

    def test_exhausted_retries_raise(self, monkeypatch):
        import urllib.error
        monkeypatch.setattr(ai_client.urllib.request, "urlopen",
                            lambda req, timeout=None: (_ for _ in ()).throw(
                                urllib.error.URLError("down")))
        monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
        with pytest.raises(AIError, match="down"):
            self.make_client().chat("x")

    def test_polish_empty_response_returns_transcript(self, monkeypatch):
        # model answers with thinking only -> cleaned empty -> raw kept
        monkeypatch.setattr(ai_client.urllib.request, "urlopen",
                            lambda req, timeout=None: self._respond(
                                {"choices": [{"message": {"content": "<think>   </think>"}}]}))
        out = self.make_client().polish("keep me")
        assert out == "keep me"

    def test_auth_header_sent_when_key_present(self, monkeypatch):
        seen = {}

        def grab(req, timeout=None):
            seen["auth"] = req.headers.get("Authorization")
            return self._respond({"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr(ai_client.urllib.request, "urlopen", grab)
        self.make_client(api_key="sk-test").chat("x")
        assert seen["auth"] == "Bearer sk-test"
