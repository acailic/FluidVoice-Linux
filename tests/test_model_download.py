"""GGUF download mechanics — urlopen fakes, never any network."""
from __future__ import annotations

import urllib.error

import pytest

from fluidvoice import model_catalog, model_download


class FakeResp:
    def __init__(self, chunks, length=None):
        self._chunks = list(chunks)
        self.headers = {}
        if length is not None:
            self.headers["Content-Length"] = str(length)

    def read(self, n):
        if not self._chunks:
            return b""
        first = self._chunks[0]
        if isinstance(first, Exception):
            raise self._chunks.pop(0)
        return self._chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path


def test_happy_path_streams_and_renames(cache, monkeypatch):
    chunks = [b"ab", b"cd", b"ef"]
    seen_req = {}

    def fake_urlopen(req, timeout=None):
        seen_req["req"] = req
        return FakeResp(chunks, length=6)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    events: list[tuple[int, int | None]] = []
    dest = model_download.download_gguf(
        "ggml-base.bin", progress=lambda b, t: events.append((b, t)))
    assert dest == model_catalog.gguf_path("ggml-base.bin")
    assert dest.read_bytes() == b"abcdef"
    assert list(dest.parent.iterdir()) == [dest]  # no .part left
    assert events[0] == (0, 6)
    assert events[-1] == (6, 6)
    assert [b for b, _ in events] == sorted(b for b, _ in events)  # monotonic
    # URL fidelity + UA
    assert seen_req["req"].full_url == \
        model_catalog.GGUF_CATALOG["ggml-base.bin"]["url"]
    assert "FluidVoiceLinux" in seen_req["req"].headers["User-agent"]


def test_no_content_length_still_succeeds(cache, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp([b"xyz"]))
    events: list[tuple[int, int | None]] = []
    dest = model_download.download_gguf(
        "ggml-base.en.bin", progress=lambda b, t: events.append((b, t)))
    assert dest.read_bytes() == b"xyz"
    assert events and all(t is None for _, t in events)
    assert not dest.with_name(dest.name + ".part").exists()


def test_midstream_failure_cleans_up(cache, monkeypatch):
    def fake_urlopen(req, timeout=None):
        return FakeResp([b"par", OSError("socket reset"), b"tial"])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(OSError, match="socket reset"):
        model_download.download_gguf("ggml-small.bin")
    assert list(model_catalog.gguf_dir().iterdir()) == []  # nothing at all


def test_http_error_propagates(cache, monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        model_download.download_gguf("ggml-medium.bin")
    assert not model_catalog.gguf_path("ggml-medium.bin").exists()
    assert model_catalog.gguf_dir().is_dir()  # parent still created


def test_truncated_download_raises(cache, monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp([b"only"], length=99))
    with pytest.raises(OSError, match="truncated"):
        model_download.download_gguf("ggml-large-v3.bin")
    assert not model_catalog.gguf_path("ggml-large-v3.bin").exists()
    assert not model_catalog.gguf_dir().joinpath(
        "ggml-large-v3.bin.part").exists()


def test_unknown_gguf_name_rejected(cache):
    with pytest.raises(ValueError, match="unknown gguf model"):
        model_download.download_gguf("nope.bin")


def test_existing_file_is_noop(cache, monkeypatch):
    model_catalog.gguf_dir().mkdir(parents=True)
    dest = model_catalog.gguf_path("ggml-base.bin")
    dest.write_bytes(b"already here")
    called = []
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: called.append(a))
    out = model_download.download_gguf("ggml-base.bin")
    assert out == dest and dest.read_bytes() == b"already here"
    assert called == []  # urlopen never touched
