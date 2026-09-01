from __future__ import annotations

import pytest

from fluidvoice import backends
from fluidvoice.config import DEFAULTS


def cfg(**model_overrides):
    import copy
    c = copy.deepcopy(DEFAULTS)
    c["model"].update(model_overrides)
    return c


class TestResolveModelName:
    def test_auto_gpu_default(self, monkeypatch):
        monkeypatch.setattr(backends, "cuda_available", lambda: True)
        assert backends.resolve_model_name("auto") == "small"

    def test_auto_cpu_default(self, monkeypatch):
        monkeypatch.setattr(backends, "cuda_available", lambda: False)
        assert backends.resolve_model_name("auto") == "base"

    def test_aliases(self):
        assert backends.resolve_model_name("turbo") == "large-v3-turbo"
        assert backends.resolve_model_name("LARGE") == "large-v3"
        assert backends.resolve_model_name(" large-v3-turbo ") == "large-v3-turbo"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="unknown model"):
            backends.resolve_model_name("gpt-4o-audio")

    def test_every_resolvable_model_has_a_repo(self):
        for name in ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"):
            assert name in backends.FW_MODEL_REPOS


class TestLoadBackendSelection:
    """Backend priority with faked availability - no real models touched."""

    @pytest.fixture()
    def fakes(self, monkeypatch):
        from fluidvoice.backends import faster_whisper_backend as fw
        from fluidvoice.backends import torch_whisper as tw
        from fluidvoice.backends import whisper_cpp as wc

        made: list[str] = []

        class FakeFW:
            name = "faster-whisper"

            def __init__(self, c):
                made.append("faster-whisper")

        class FakeTorch:
            name = "whisper-torch"

            def __init__(self, c):
                made.append("whisper-torch")

        class FakeCpp:
            name = "whisper.cpp"

            def __init__(self, c):
                made.append("whisper.cpp")

        monkeypatch.setattr(fw, "FasterWhisperBackend", FakeFW)
        monkeypatch.setattr(tw, "TorchWhisperBackend", FakeTorch)
        monkeypatch.setattr(wc, "WhisperCppBackend", FakeCpp)
        return made

    def test_faster_whisper_gpu_wins(self, monkeypatch, fakes):
        monkeypatch.setattr(backends, "_import_ok", lambda m: m == "faster_whisper")
        monkeypatch.setattr(backends, "preload_cuda_libs", lambda: True)
        b = backends.load_backend(cfg())
        assert b.name == "faster-whisper"

    def test_torch_gpu_when_fw_cpu_only(self, monkeypatch, fakes):
        monkeypatch.setattr(backends, "_import_ok", lambda m: True)
        monkeypatch.setattr(backends, "preload_cuda_libs", lambda: False)
        monkeypatch.setattr(backends, "cuda_available", lambda: True)
        b = backends.load_backend(cfg())
        assert b.name == "whisper-torch"

    def test_faster_whisper_cpu_when_no_gpu(self, monkeypatch, fakes):
        monkeypatch.setattr(backends, "_import_ok", lambda m: m == "faster_whisper")
        monkeypatch.setattr(backends, "preload_cuda_libs", lambda: False)
        monkeypatch.setattr(backends, "cuda_available", lambda: False)
        b = backends.load_backend(cfg())
        assert b.name == "faster-whisper"

    def test_whisper_cpp_explicit(self, monkeypatch, fakes):
        monkeypatch.setattr(backends, "_whispercpp_binary", lambda: "/usr/bin/whisper-cli")
        monkeypatch.setattr(backends, "_import_ok", lambda m: False)
        b = backends.load_backend(cfg(backend="whisper.cpp",
                                      whispercpp_model="/models/ggml-base.bin"))
        assert b.name == "whisper.cpp"

    def test_nothing_available(self, monkeypatch, fakes):
        monkeypatch.setattr(backends, "_import_ok", lambda m: False)
        monkeypatch.setattr(backends, "_whispercpp_binary", lambda: None)
        with pytest.raises(RuntimeError, match="no speech backend"):
            backends.load_backend(cfg())

    def test_explicit_unknown_backend(self):
        with pytest.raises(ValueError, match="unknown backend"):
            backends.load_backend(cfg(backend="deepgram"))


class TestWhisperCppBinary:
    def test_finds_known_names(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which",
                            lambda n: f"/usr/bin/{n}" if n == "whisper-cli" else None)
        assert backends._whispercpp_binary() == "/usr/bin/whisper-cli"

    def test_none_found(self, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda n: None)
        assert backends._whispercpp_binary() is None


class TestUpstreamNameAliases:
    def test_whisper_prefix_aliases(self):
        assert backends.resolve_model_name("whisper-small") == "small"
        assert backends.resolve_model_name("whisper-large-turbo") == "large-v3-turbo"
        assert backends.resolve_model_name("WHISPER-BASE") == "base"
