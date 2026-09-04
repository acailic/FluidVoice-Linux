"""GGUF + Parakeet download mechanics — urlopen fakes, never any network."""
from __future__ import annotations

import hashlib
import io
import tarfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

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
    assert "SayItErmano" in seen_req["req"].headers["User-agent"]


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


# -- parakeet tarball downloads -------------------------------------------------

PK_FILES = {"encoder.int8.onnx": b"ENC", "decoder.int8.onnx": b"DEC",
            "joiner.int8.onnx": b"JOIN", "tokens.txt": b"<unk> 0\n"}


def make_tarball(path: Path, files: dict[str, bytes] | None = None,
                 top: str = "sherpa-onnx-nemo-parakeet-x-int8") -> bytes:
    data = files if files is not None else PK_FILES
    with tarfile.open(path, "w:bz2") as tf:
        for name, blob in data.items():
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(blob)
            tf.addfile(info, io.BytesIO(blob))
    return path.read_bytes()


def pk_entry(tar_path: Path, files: dict[str, bytes] | None = None,
             tarball_sha: str | None = None) -> dict:
    data = files if files is not None else PK_FILES
    return {
        "size": "~tiny", "langs": "en", "note": "fixture",
        "url": "http://fake/parakeet.tar.bz2",
        "tarball_sha256": tarball_sha or hashlib.sha256(tar_path.read_bytes()).hexdigest(),
        "files": {n: hashlib.sha256(b).hexdigest() for n, b in data.items()},
        "features": {"sample_rate": 16000, "n_mels": 128, "n_fft": 512,
                     "win": 400, "hop": 160, "fmin": 0.0, "fmax": 8000.0},
    }


class TestDownloadParakeet:
    NAME = "pk-fixture"

    @pytest.fixture()
    def pk(self, cache, monkeypatch, tmp_path):
        """A fixture catalog entry + its matching tarball on a fake server."""
        tar = tmp_path / "t.tar.bz2"
        blob = make_tarball(tar)
        entry = pk_entry(tar)
        monkeypatch.setattr(model_catalog, "PARAKEET_CATALOG",
                            {self.NAME: entry})
        serve = {"blob": blob}

        def fake_urlopen(req, timeout=None):
            return FakeResp([serve["blob"]], length=len(serve["blob"]))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return SimpleNamespace(entry=entry, serve=serve, fake=fake_urlopen)

    def test_happy_path(self, cache, monkeypatch, pk):
        events: list[tuple[int, int | None]] = []
        d = model_download.download_parakeet(
            self.NAME, progress=lambda b, t: events.append((b, t)))
        assert d == model_catalog.parakeet_model_dir(self.NAME)
        assert sorted(p.name for p in d.iterdir()) == sorted(PK_FILES)
        for name, want in PK_FILES.items():
            assert (d / name).read_bytes() == want
        total = len(pk.serve["blob"])
        assert events[0] == (0, total)
        assert events[-1] == (total, total)
        assert [b for b, _ in events] == sorted(b for b, _ in events)
        # nothing left behind: no tarball, no stage, no .part
        leftovers = [p.name for p in model_catalog.parakeet_dir().iterdir()]
        assert leftovers == [self.NAME]

    def test_tarball_sha_mismatch_cleans_up(self, cache, monkeypatch, pk, tmp_path):
        tar = tmp_path / "bad.tar.bz2"
        make_tarball(tar, {**PK_FILES, "tokens.txt": b"tampered\n"})
        pk.serve["blob"] = tar.read_bytes()  # valid bz2, wrong bytes
        with pytest.raises(OSError, match="checksum mismatch.*tarball"):
            model_download.download_parakeet(self.NAME)
        assert list(model_catalog.parakeet_dir().iterdir()) == []

    def test_midstream_failure_leaves_nothing(self, cache, monkeypatch, pk):
        blob = pk.serve["blob"]
        half = len(blob) // 2

        def flaky(req, timeout=None):
            return FakeResp([blob[:half], OSError("socket reset"), blob[half:]])

        monkeypatch.setattr(urllib.request, "urlopen", flaky)
        with pytest.raises(OSError, match="socket reset"):
            model_download.download_parakeet(self.NAME)
        assert list(model_catalog.parakeet_dir().iterdir()) == []

    def test_inner_file_sha_mismatch_cleans_up(self, cache, monkeypatch, pk, tmp_path):
        tampered = {**PK_FILES, "joiner.int8.onnx": b"EVIL"}
        tar = tmp_path / "t2.tar.bz2"
        blob = make_tarball(tar, tampered)
        entry = pk_entry(tar, files=PK_FILES, tarball_sha=hashlib.sha256(blob).hexdigest())
        monkeypatch.setattr(model_catalog, "PARAKEET_CATALOG",
                            {self.NAME: entry})
        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda req, timeout=None: FakeResp([blob], length=len(blob)))
        with pytest.raises(OSError, match="checksum mismatch.*joiner"):
            model_download.download_parakeet(self.NAME)
        assert list(model_catalog.parakeet_dir().iterdir()) == []

    def test_missing_member_raises(self, cache, monkeypatch, pk, tmp_path):
        partial = {k: v for k, v in PK_FILES.items() if k != "tokens.txt"}
        tar = tmp_path / "t3.tar.bz2"
        blob = make_tarball(tar, partial)
        entry = pk_entry(tar, files=PK_FILES,
                         tarball_sha=hashlib.sha256(blob).hexdigest())
        monkeypatch.setattr(model_catalog, "PARAKEET_CATALOG",
                            {self.NAME: entry})
        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda req, timeout=None: FakeResp([blob], length=len(blob)))
        with pytest.raises(OSError, match="missing: tokens.txt"):
            model_download.download_parakeet(self.NAME)
        assert list(model_catalog.parakeet_dir().iterdir()) == []

    def test_already_downloaded_is_noop(self, cache, monkeypatch, pk):
        d = model_catalog.parakeet_model_dir(self.NAME)
        d.mkdir(parents=True)
        for name, want in PK_FILES.items():
            (d / name).write_bytes(want)
        called = []
        monkeypatch.setattr(urllib.request, "urlopen",
                            lambda *a, **k: called.append(a))
        out = model_download.download_parakeet(self.NAME)
        assert out == d and called == []

    def test_unknown_name_rejected(self, cache):
        with pytest.raises(ValueError, match="unknown parakeet model"):
            model_download.download_parakeet("parakeet-nope")

    def test_stale_stage_removed_on_fresh_run(self, cache, monkeypatch, pk):
        stale = model_catalog.parakeet_dir() / f".{self.NAME}.tmp-1"
        stale.mkdir(parents=True)
        (stale / "encoder.int8.onnx").write_bytes(b"junk")
        d = model_download.download_parakeet(self.NAME)
        assert (d / "tokens.txt").read_bytes() == PK_FILES["tokens.txt"]
        assert not stale.exists()


class TestDownloadFiles:
    def test_aggregate_progress_across_files(self, cache, monkeypatch, tmp_path):
        a, b = b"aaa", b"bb"
        urls = {"http://x/a": a, "http://x/b": b}

        def fake_urlopen(req, timeout=None):
            blob = urls[req.full_url]
            return FakeResp([blob], length=len(blob))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        events: list[tuple[int, int | None]] = []
        dest = tmp_path / "multi"
        out = model_download.download_files(
            [{"name": "a.bin", "url": "http://x/a",
              "sha256": hashlib.sha256(a).hexdigest(), "size": len(a)},
             {"name": "b.bin", "url": "http://x/b",
              "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}],
            dest, progress=lambda done, t: events.append((done, t)))
        assert out == dest
        assert (dest / "a.bin").read_bytes() == a
        assert (dest / "b.bin").read_bytes() == b
        assert events[0] == (0, 5)
        assert events[-1] == (5, 5)
        assert [d for d, _ in events] == sorted(d for d, _ in events)

    def test_bad_sha_aborts_and_leaves_no_dest(self, cache, monkeypatch, tmp_path):
        a = b"aaa"
        monkeypatch.setattr(
            urllib.request, "urlopen",
            lambda req, timeout=None: FakeResp([a], length=len(a)))
        dest = tmp_path / "multi"
        with pytest.raises(OSError, match="checksum mismatch"):
            model_download.download_files(
                [{"name": "a.bin", "url": "http://x/a",
                  "sha256": "0" * 64, "size": len(a)}], dest)
        assert not dest.exists()
        assert list(tmp_path.iterdir()) == []  # staging dir gone too
