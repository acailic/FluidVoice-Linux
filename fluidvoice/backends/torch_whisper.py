"""openai-whisper (torch) backend - used when a CUDA torch install already exists."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ALIASES, cuda_available, resolve_model_name


class TorchWhisperBackend:
    name = "whisper-torch"

    def __init__(self, cfg: dict):
        import whisper  # noqa: openai-whisper

        self._whisper = whisper
        mcfg = cfg["model"]
        self.model_name = resolve_model_name(mcfg["name"])
        self.language = cfg["general"]["language"] or None
        self.device = mcfg["device"]
        if self.device == "auto":
            self.device = "cuda" if cuda_available() else "cpu"
        self._model = None  # lazy load

    def warmup(self) -> None:
        self._load()

    def _load(self) -> None:
        if self._model is None:
            self._model = self._whisper.load_model(self.model_name, device=self.device)

    def transcribe(self, wav_path: Path, language: str | None = None) -> dict[str, Any]:
        self._load()
        lang = language or self.language
        if lang == "auto":
            lang = None
        result = self._model.transcribe(str(wav_path), language=lang,
                                        fp16=self.device == "cuda")
        segments = [{"start": round(s.get("start", 0.0), 3),
                     "end": round(s.get("end", 0.0), 3),
                     "text": (s.get("text") or "").strip()}
                    for s in result.get("segments", [])]
        return {"text": result.get("text", "").strip(), "language": result.get("language"),
                "duration": None, "segments": segments}
