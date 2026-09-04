"""faster-whisper backend (default). CUDA when possible, CPU int8 otherwise."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import FW_MODEL_REPOS, cuda_available, preload_cuda_libs, resolve_model_name


class FasterWhisperBackend:
    name = "faster-whisper"

    def __init__(self, cfg: dict):
        preload_cuda_libs()  # must run before ctranslate2 loads its CUDA libs
        from faster_whisper import WhisperModel  # noqa: deferred import

        self._WhisperModel = WhisperModel
        mcfg = cfg["model"]
        self.model_name = resolve_model_name(mcfg["name"])
        self.language = cfg["general"]["language"] or None
        device = mcfg["device"]
        compute = mcfg["compute"]
        if device == "auto":
            device = "cuda" if cuda_available() else "cpu"
        if compute == "auto":
            compute = "float16" if device == "cuda" else "int8"
        self.device, self.compute = device, compute
        self._model: Any = None  # lazy load (first transcription)

    def warmup(self) -> None:
        self._load()

    def _load(self) -> None:
        if self._model is not None:
            return
        from .. import paths
        download_root = str(paths.models_dir() / "faster-whisper")
        try:
            self._model = self._WhisperModel(
                FW_MODEL_REPOS[self.model_name] if self.model_name in FW_MODEL_REPOS else self.model_name,
                device=self.device, compute_type=self.compute,
                download_root=download_root,
            )
        except Exception:
            if self.device == "cuda":
                # Missing cuDNN/cuBLAS etc. - fall back to CPU int8.
                self.device, self.compute = "cpu", "int8"
                self._model = self._WhisperModel(
                    FW_MODEL_REPOS.get(self.model_name, self.model_name),
                    device=self.device, compute_type=self.compute,
                    download_root=download_root,
                )
            else:
                raise

    def transcribe(self, wav_path: Path, language: str | None = None) -> dict[str, Any]:
        self._load()
        lang = language or self.language
        if lang == "auto":
            lang = None
        segments, info = self._model.transcribe(
            str(wav_path), language=lang, vad_filter=False, beam_size=1,
        )
        texts, segs = [], []
        for seg in segments:  # generator - consume once, reuse for text AND segments
            texts.append(seg.text)
            segs.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                         "text": seg.text.strip(),
                         "avg_logprob": round(getattr(seg, "avg_logprob", 0.0), 3)})
        return {"text": "".join(texts).strip(), "language": info.language,
                "duration": info.duration, "segments": segs}
