"""Minimal OpenAI-compatible chat client for the AI polish step.

- Endpoint: <base_url>/chat/completions (path appended only when the base URL
  does not already end with /chat/completions, /api/chat or /api/generate,
  mirroring FluidVoice's LLMClient).
- Dictation params: stream=false, temperature from config (default 0.2).
- Responses pass through the same <think>-tag stripping as upstream.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from .prompts import default_dictation_prompt, render_dictation_user_message

THINK_RE = re.compile(r"<think(?:ing)?>([\s\S]*?)</think(?:ing)?>")
ORPHAN_CLOSE_RE = re.compile(r"^([\s\S]*?)</think(?:ing)?>")
STRAY_TAG_RE = re.compile(r"</?think(?:ing)?>")


def strip_thinking(text: str) -> str:
    """Port of FluidVoice's StripThinkingTags (incl. Nemotron-style orphan close)."""
    if not text:
        return text
    text = THINK_RE.sub("", text)
    if "</think>" in text or "</thinking>" in text:
        # thinking emitted without an opening tag: keep only what follows the close
        m = ORPHAN_CLOSE_RE.match(text)
        if m:
            text = text[m.end():]
    text = STRAY_TAG_RE.sub("", text)
    return text.strip()


class AIError(RuntimeError):
    pass


def _endpoint(base_url: str) -> str:
    base = base_url.rstrip("/")
    for suffix in ("/chat/completions", "/api/chat", "/api/generate"):
        if base.endswith(suffix):
            return base
    return base + "/chat/completions"


class AIClient:
    def __init__(self, cfg: dict):
        ai = cfg["ai"]
        self.base_url = ai["base_url"].rstrip("/")
        self.model = ai.get("model", "")
        self.temperature = float(ai.get("temperature", 0.2))
        self.timeout = float(ai.get("timeout_seconds", 60))
        self.retries = int(ai.get("max_retries", 3))
        self.api_key = ai.get("api_key", "") or os.environ.get(ai.get("api_key_env", ""), "")
        self.system_prompt = default_dictation_prompt()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def polish(self, transcript: str, system_prompt: str | None = None) -> str:
        """Clean a raw transcript through the configured chat model."""
        if not self.configured:
            raise AIError("AI polish enabled but base_url/model not configured")
        prompt = (system_prompt or self.system_prompt).strip()
        user_message = render_dictation_user_message(prompt, transcript)
        content = self.chat(user_message)
        cleaned = strip_thinking(content)
        return cleaned or transcript

    def chat(self, user_message: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": user_message}],
            "temperature": self.temperature,
            "stream": False,
        }
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(_endpoint(self.base_url), data=payload,
                                     headers=headers, method="POST")
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode(errors="replace")[:300]
                except Exception:
                    pass
                last_err = AIError(f"HTTP {e.code}: {detail}")
                if e.code in (400, 401, 403, 404, 422):
                    raise last_err  # config errors won't fix themselves
            except Exception as e:  # noqa: BLE001 - transport errors retry
                last_err = AIError(str(e))
            if attempt < self.retries:
                time.sleep(0.2 * attempt)
        raise last_err or AIError("request failed")
