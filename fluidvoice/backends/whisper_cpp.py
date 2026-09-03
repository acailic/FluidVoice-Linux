"""whisper.cpp backend - uses an external whisper-cli binary + ggml/gguf model."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import _whispercpp_binary


class WhisperCppBackend:
    name = "whisper.cpp"

    def __init__(self, cfg: dict):
        self.binary = _whispercpp_binary()
        if not self.binary:
            raise RuntimeError("whisper.cpp binary not found (whisper-cli/whisper-cpp)")
        self.model = (cfg["model"].get("whispercpp_model") or "").strip()
        if not self.model:
            raise RuntimeError("model.whispercpp_model path is required for the whisper.cpp backend")
        self.language = cfg["general"]["language"] or "auto"

    def transcribe(self, wav_path: Path, language: str | None = None) -> dict[str, Any]:
        lang = language or self.language or "auto"
        args = [self.binary, "-m", self.model, "-f", str(wav_path), "-nt", "-np"]
        if lang != "auto":
            args += ["-l", lang]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError(f"whisper.cpp failed: {proc.stderr.strip()[:500]}")
        text = " ".join(line.strip() for line in proc.stdout.splitlines() if line.strip())
        return {"text": text.strip(), "language": None if lang == "auto" else lang,
                "duration": None,
                # segments not exposed in v1: needs whisper-cli -ml parsing
                "segments": []}
