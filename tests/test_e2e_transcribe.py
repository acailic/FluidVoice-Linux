"""End-to-end transcription test (downloads a ~75 MB model + 1 MB sample).

Run with:  pytest -m slow tests/test_e2e_transcribe.py
"""
import ssl
import urllib.request
from pathlib import Path

import pytest

from fluidvoice import backends
from fluidvoice.config import DEFAULTS
from fluidvoice.processing import post_process

pytestmark = pytest.mark.slow

JFK_URL = "https://github.com/openai/whisper/raw/main/tests/jfk.flac"


@pytest.fixture(scope="module")
def jfk(tmp_path_factory) -> Path:
    dst = tmp_path_factory.mktemp("audio") / "jfk.flac"
    with urllib.request.urlopen(JFK_URL, timeout=60) as resp:
        dst.write_bytes(resp.read())
    return dst


@pytest.fixture(scope="module")
def backend():
    cfg = dict(DEFAULTS)
    cfg["model"] = dict(DEFAULTS["model"], name="tiny")  # smallest download
    return backends.load_backend(cfg)


def test_transcribe_jfk(jfk: Path, backend):
    result = backend.transcribe(jfk, language="en")
    text = result["text"].lower()
    assert "fellow americans" in text or "my fellow" in text
    assert "country" in text


def test_pipeline_leaves_clean_transcript_untouched(jfk: Path, backend):
    result = backend.transcribe(jfk, language="en")
    cfg = dict(DEFAULTS)
    out = post_process(result["text"], cfg)
    # no "literal" commands were spoken -> text unchanged apart from fillers
    assert out.strip().lower().startswith("and so my fellow")
