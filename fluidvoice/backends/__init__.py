"""Speech-to-text backends with auto-detection.

Priority under "auto":
  1. faster-whisper  (CUDA if the NVIDIA runtime libs can be resolved, else CPU int8)
  2. whisper-torch   (openai-whisper; used when torch+CUDA is already installed)
  3. whisper.cpp     (external binary + ggml model)
"""
from __future__ import annotations

import ctypes
import glob
import os
from typing import Any

# faster-whisper model names -> HuggingFace repos
FW_MODEL_REPOS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}
ALIASES = {"turbo": "large-v3-turbo", "large": "large-v3", "large-v3-turbo": "large-v3-turbo"}
# Accept upstream's raw value names ("whisper-small", "whisper-large-turbo", ...)
ALIASES.update({
    "whisper-tiny": "tiny", "whisper-base": "base", "whisper-small": "small",
    "whisper-medium": "medium", "whisper-large": "large-v3",
    "whisper-large-v3": "large-v3", "whisper-large-turbo": "large-v3-turbo",
    "whisper-large-v3-turbo": "large-v3-turbo",
})

_cuda_libs_preloaded: bool | None = None


def preload_cuda_libs() -> bool:
    """Preload cudnn/cublas shipped by pip `nvidia-*` packages (e.g. installed by
    a CUDA torch wheel) so ctranslate2 can use the GPU. Returns True on success.

    dlopen() resolves by absolute path here; once loaded, ctranslate2's own
    dlopen("libcudnn.so.9") finds the already-loaded sonames.
    """
    global _cuda_libs_preloaded
    if _cuda_libs_preloaded is not None:
        return _cuda_libs_preloaded

    wanted = ["libcudnn.so.9", "libcublas.so.12", "libcublasLt.so.12"]
    search_dirs: list[str] = []
    # pip nvidia packages live inside torch's venv/site-packages
    import site
    site_dirs = list(site.getsitepackages())
    if site.ENABLE_USER_SITE:
        site_dirs.append(site.getusersitepackages())
    for sp in site_dirs:
        search_dirs += glob.glob(os.path.join(sp, "nvidia", "*", "lib"))
    # also classic locations
    search_dirs += ["/usr/local/cuda/lib64", "/usr/lib/x86_64-linux-gnu"]

    ok = 0
    for soname in wanted:
        for d in search_dirs:
            full = os.path.join(d, soname)
            if os.path.exists(full):
                try:
                    ctypes.CDLL(full, mode=ctypes.RTLD_GLOBAL)
                    ok += 1
                except OSError:
                    pass
                break
    # All three (or at least cudnn + cublas) needed for a safe GPU attempt.
    _cuda_libs_preloaded = ok >= 3
    return _cuda_libs_preloaded


def cuda_available() -> bool:
    if os.environ.get("FLUIDVOICE_FORCE_CPU") == "1":
        return False
    if preload_cuda_libs():
        return True
    # torch may still have working CUDA even if the nvidia pip layout differs
    try:
        import torch  # noqa: F401
        import torch.cuda  # noqa: F401
        if torch.cuda.is_available():
            return True
    except Exception:
        pass
    return False


def _import_ok(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _whispercpp_binary() -> str | None:
    import shutil
    for name in ("whisper-cli", "whisper-cpp", "whisper.cpp", "whisper-main"):
        p = shutil.which(name)
        if p:
            return p
    return None


def backend_status() -> dict[str, str]:
    """Human-readable availability report for `fluidvoice doctor`."""
    status = {}
    if _import_ok("whisper"):
        try:
            import torch
            gpu = "GPU (torch.cuda)" if torch.cuda.is_available() else "CPU"
        except Exception:
            gpu = "?"
        status["whisper-torch"] = f"available ({gpu})"
    else:
        status["whisper-torch"] = "not installed (pip install openai-whisper)"
    if _import_ok("faster_whisper"):
        status["faster-whisper"] = f"available ({'GPU possible' if preload_cuda_libs() else 'CPU int8'})"
    else:
        status["faster-whisper"] = "not installed (pip install faster-whisper)"
    status["whisper.cpp"] = _whispercpp_binary() or "binary not found on PATH"
    return status


class Backend:
    name = "backend"

    def transcribe(self, wav_path: Path, language: str | None) -> dict[str, Any]:
        raise NotImplementedError

    def warmup(self) -> None:  # optional model preload/download
        pass


def resolve_model_name(name: str) -> str:
    name = ALIASES.get(name.strip().lower(), name.strip().lower())
    if name in ("", "auto"):
        return "small" if cuda_available() else "base"
    if name not in FW_MODEL_REPOS:
        raise ValueError(f"unknown model '{name}' (choose from {sorted(FW_MODEL_REPOS)})")
    return name


def load_backend(cfg: dict) -> Backend:
    from .faster_whisper_backend import FasterWhisperBackend
    from .torch_whisper import TorchWhisperBackend
    from .whisper_cpp import WhisperCppBackend

    wanted = cfg["model"]["backend"]
    if wanted == "auto":
        # 1. faster-whisper GPU (needs cuBLAS 12 + cuDNN 9 sonames loadable)
        if _import_ok("faster_whisper") and preload_cuda_libs():
            return FasterWhisperBackend(cfg)
        # 2. torch GPU (a CUDA torch install is already on the system)
        if _import_ok("whisper") and cuda_available():
            return TorchWhisperBackend(cfg)
        # 3. faster-whisper CPU int8
        if _import_ok("faster_whisper"):
            return FasterWhisperBackend(cfg)
        if _whispercpp_binary() and cfg["model"].get("whispercpp_model"):
            return WhisperCppBackend(cfg)
        raise RuntimeError(
            "no speech backend available - run `fluidvoice doctor` "
            "(pip install faster-whisper)"
        )
    if wanted == "faster-whisper":
        return FasterWhisperBackend(cfg)
    if wanted in ("whisper-torch", "torch", "openai-whisper"):
        return TorchWhisperBackend(cfg)
    if wanted in ("whisper.cpp", "whispercpp"):
        return WhisperCppBackend(cfg)
    raise ValueError(f"unknown backend '{wanted}'")
