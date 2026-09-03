"""GGUF catalog: curated whisper.cpp ggml models + managed-cache probes."""
from __future__ import annotations

from fluidvoice import model_catalog, paths

BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"


def test_gguf_catalog_completeness():
    assert set(model_catalog.GGUF_CATALOG) == {
        "ggml-base.bin", "ggml-base.en.bin",
        "ggml-small.bin", "ggml-small.en.bin",
        "ggml-medium.bin", "ggml-medium.en.bin",
        "ggml-large-v3.bin",
    }
    for name, info in model_catalog.GGUF_CATALOG.items():
        assert set(info) == {"size", "langs", "note", "url"}, name
        assert info["url"] == BASE + name


def test_gguf_path_is_managed_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    p = model_catalog.gguf_path("ggml-base.bin")
    assert p == paths.models_dir() / "whisper.cpp" / "ggml-base.bin"


def test_gguf_downloaded_true_false(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert model_catalog.gguf_downloaded("ggml-base.bin") is False
    model_catalog.gguf_dir().mkdir(parents=True)
    model_catalog.gguf_path("ggml-base.bin").write_bytes(b"x")
    assert model_catalog.gguf_downloaded("ggml-base.bin") is True
    # unknown name is never "downloaded" (and never writes a path)
    assert model_catalog.gguf_downloaded("ggml-bogus.bin") is False
