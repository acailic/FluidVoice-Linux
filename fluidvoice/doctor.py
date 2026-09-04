"""`sayit-ermano doctor` - environment report."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from . import __version__, backends, paths
from .config import load_config


def _gtk_available() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False


def _whispercpp_lines(cfg: dict) -> list[str]:
    """Human-readable whisper.cpp resolution: binary + model path or hint."""
    from . import model_catalog
    binary = backends._whispercpp_binary()
    lines = [f"  binary: {binary or 'not found (install whisper-cli)'}"]
    raw = (cfg.get("model", {}).get("whispercpp_model") or "").strip()
    if not raw:
        lines.append("  model: not set (a catalog name like 'ggml-base.bin' "
                     "or a path — see Settings → Models)")
        return lines
    if "/" in raw or raw.startswith("~"):
        p = Path(raw).expanduser()
        lines.append(f"  model: {p} ({'found' if p.is_file() else 'MISSING'})")
    elif raw in model_catalog.GGUF_CATALOG:
        p = model_catalog.gguf_path(raw)
        lines.append(f"  model: {raw} -> {p} "
                     f"({'downloaded' if p.is_file() else 'not downloaded - get it in Settings -> Models'})")
    else:
        lines.append(f"  model: unknown name '{raw}' "
                     f"(catalog: {', '.join(sorted(model_catalog.GGUF_CATALOG))})")
    have = (sorted(p.name for p in model_catalog.gguf_dir().glob("ggml-*.bin")
                   if p.is_file())
            if model_catalog.gguf_dir().is_dir() else [])
    lines.append("  downloaded ggml models: " + (", ".join(have) if have else "none"))
    return lines


def _parakeet_lines(cfg: dict) -> list[str]:
    """Parakeet (ONNX) report: runtime, providers, per-model download state."""
    from . import model_catalog
    try:
        import onnxruntime as ort
        provs = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider")
                 if p in ort.get_available_providers()]
        where = "CUDA+CPU" if "CUDAExecutionProvider" in provs else "CPU"
        lines = [f"  onnxruntime: {ort.__version__} ({where})"]
    except Exception:
        return ["  onnxruntime: not installed (pip install onnxruntime)"]
    for name, info in model_catalog.PARAKEET_CATALOG.items():
        d = model_catalog.parakeet_model_dir(name)
        if model_catalog.parakeet_downloaded(name):
            lines.append(f"  {name}: downloaded ({d})")
        else:
            missing = ", ".join(f for f in info["files"]
                                 if not (d / f).is_file()) or "incomplete"
            lines.append(f"  {name}: not downloaded — missing: {missing} "
                         "(get it in Settings -> Models)")
    if (cfg.get("model", {}).get("backend") or "") == "parakeet":
        raw = str(cfg.get("model", {}).get("name", "")).strip() or "auto"
        if raw in ("auto", ""):
            raw = model_catalog.PARAKEET_DEFAULT_MODEL
        if raw in model_catalog.PARAKEET_CATALOG:
            mark = ("downloaded" if model_catalog.parakeet_downloaded(raw)
                    else "not downloaded")
            lines.append(f"  active model: {raw} ({mark})")
        else:
            lines.append(f"  active model: unknown name '{raw}' "
                         f"(catalog: "
                         f"{', '.join(sorted(model_catalog.PARAKEET_CATALOG))})")
    return lines


def _formatting_lines(cfg: dict) -> list[str]:
    """Chat/terminal formatting resolution: one line per key."""
    p = cfg.get("processing", {})
    i = cfg.get("insertion", {})
    apps = cfg.get("general", {}).get("terminal_apps") or []
    names = ", ".join(apps) if apps else "none"
    return [
        f"  slash/mention squeeze: "
        f"{'on' if p.get('slash_mention_squeeze', True) else 'off'} "
        f"(processing.slash_mention_squeeze)",
        f"  terminal autocomplete space: "
        f"{'on' if i.get('terminal_autocomplete_space', True) else 'off'} "
        f"(insertion.terminal_autocomplete_space)",
        f"  terminal_apps ({len(apps)}): {names} "
        f"(spoken-send Enter suppressed here)",
    ]


def _models_cache_lines(cfg: dict) -> list[str]:
    """Models-cache report: one line per cached entry (with the ACTIVE
    marker), a total, and a note that the legacy huggingface/hub location
    is not manageable here."""
    from . import model_catalog
    entries = model_catalog.cached_models()
    lines = [f"models cache: {paths.models_dir()}"]
    active = backends.config_model_key(cfg)
    for e in entries:
        mark = " · ACTIVE" if active and e["name"] == active else ""
        lines.append(f"  {e['kind']} {e['name']} "
                     f"{model_catalog.human_bytes(e['bytes'])}{mark}")
    total = sum(e["bytes"] for e in entries)
    lines.append(f"  total: {len(entries)} model"
                 f"{'' if len(entries) == 1 else 's'}, "
                 f"{model_catalog.human_bytes(total)}")
    lines.append("  note: the legacy huggingface/hub cache "
                 f"({paths.cache_dir().parent / 'huggingface' / 'hub'}) "
                 "is not managed here")
    return lines


def _language_lines(cfg: dict) -> list[str]:
    """Language resolution: general.language, per-model overrides, and the
    effective language of the config's active model."""
    from . import model_catalog
    general = str((cfg.get("general", {}) or {}).get("language") or "auto")
    overrides = (cfg.get("model", {}) or {}).get("languages") or {}
    lines = [f"  general: {general} (general.language)"]
    if overrides:
        pretty = ", ".join(f"{k}={v}" for k, v in overrides.items())
        lines.append(f"  per-model overrides: {pretty} (model.languages)")
    else:
        lines.append("  per-model overrides: none (model.languages)")
    key = backends.config_model_key(cfg)
    lines.append(f"  active model {key or '-'} -> "
                 f"{backends.effective_language(cfg)}")
    m = cfg.get("model", {}) or {}
    if str(m.get("backend", "")) == "parakeet" and key:
        langs = model_catalog.PARAKEET_CATALOG.get(key, {}).get("langs", "")
        if langs == "en":
            lines.append(
                f"  note: {key} is English-only - the language code is "
                "recorded but not enforced")
    return lines


def _insertion_lines(cfg: dict) -> list[str]:
    """Insertion hardening resolution: one line per key."""
    i = cfg.get("insertion", {})
    return [
        f"  paste verification: "
        f"{'on' if i.get('verify_paste', True) else 'off'} "
        f"(insertion.verify_paste)",
        f"  terminal paste key: "
        f"{i.get('terminal_paste_key', 'ctrl+shift+v')} "
        f"(insertion.terminal_paste_key)",
    ]


def _suggestions_line(cfg: dict) -> str:
    """Dictionary-learning report: pending count + the decisions file."""
    from . import history, paths
    from .processing import dict_learn
    try:
        n = len(dict_learn.pending_suggestions(cfg, history.read_all()))
    except Exception as e:  # read-only report; never fails doctor
        return f"  dictionary suggestions: unavailable ({e})"
    return (f"  dictionary suggestions: {n} pending "
            f"({paths.dictionary_suggestions_file()})")


def _history_lines() -> list[str]:
    """History sanity report: entry count, file size, oldest entry date,
    and a warning when test-fingerprint rows (the pre-isolation suite
    pollution) are still present."""
    from . import history, paths
    hpath = paths.history_file()
    lines = [f"history: {hpath}"]
    if not hpath.exists():
        return lines + ["  entries: 0 (no history yet), test rows: 0"]
    entries = history.read_all()
    size_kb = hpath.stat().st_size / 1024
    oldest = next((e.get("ts") for e in entries if e.get("ts")), None)
    when = (time.strftime("%Y-%m-%d %H:%M", time.localtime(oldest))
            if oldest else "-")
    test_rows = history.count_test_entries(entries)
    lines.append(f"  entries: {len(entries)} ({size_kb:.1f} KB), "
                 f"oldest: {when}, test rows: {test_rows}")
    if test_rows:
        lines.append(f"  WARNING: {test_rows} test-fingerprint rows present "
                     f"\u2014 run `sayit-ermano history --scrub-tests`")
    return lines


def _hotkey_grab_line() -> list[str]:
    """Last-known hotkey grab state straight from the daemon (the same
    control-socket query the other daemon checks use). The listener tracks
    per-combo grab health and retries refused grabs, so doctor reflects
    the live truth - not a 'ready' that may be keyless."""
    from . import control
    try:
        if not paths.socket_path().exists():
            raise FileNotFoundError("no control socket")
        status = control.request("status")
    except Exception:  # noqa: BLE001 - daemon down / older daemon / timeout
        return ["  hotkey grab: unknown (daemon down)"]
    state = status.get("hotkey_grabbed")
    if state is None:
        return ["  hotkey grab: disabled (--no-hotkey or older daemon)"]
    if state is False:
        return ["  hotkey grab: BLOCKED (held by another client - daemon is "
                "retrying)"]
    return ["  hotkey grab: ok"]


def run() -> int:
    print(f"SayItErmano v{__version__} doctor\n")
    ok = True

    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    print(f"session: {session}  DISPLAY={os.environ.get('DISPLAY', '-')} "
          f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '-')}")
    if session == "x11":
        print("  X11: full experience (global hotkey + xdotool typing)")
    elif session == "wayland":
        print("  Wayland: DE-shortcut -> `sayit-ermano toggle` works; typing needs "
              "ydotool/wtype (see README)")
        ok = False

    print(f"\nconfig: {paths.config_file()} ({'exists' if paths.config_file().exists() else 'not created yet - defaults in use'})")
    for line in _history_lines():
        print(line)
    try:
        cfg = load_config(paths.config_file())
    except Exception:
        cfg = {}
    print("\ndictionary learning:")
    print(_suggestions_line(cfg))
    for line in _models_cache_lines(cfg):
        print(line)

    print("\ntools:")
    for tool, why in [
        ("pw-record", "PipeWire recording (preferred)"),
        ("parecord", "PulseAudio recording (fallback)"),
        ("xdotool", "typing text into apps (X11)"),
        ("xclip", "clipboard paste mode + restore"),
        ("notify-send", "desktop notifications"),
        ("pw-play", "start/stop sounds"),
        ("ffmpeg", "transcribe fallback for non-WAV/undecodable input"),
    ]:
        have = shutil.which(tool)
        print(f"  {'OK ' if have else '-- '}{tool}: {'found' if have else 'missing'} ({why})")
        if tool in ("pw-record", "parecord") and not have:
            ok = False
    if os.environ.get("XDG_SESSION_TYPE") == "x11" and not shutil.which("xdotool"):
        ok = False

    print("\nspeech backends:")
    try:
        for name, status in backends.backend_status().items():
            print(f"  {name}: {status}")
    except Exception as e:
        print(f"  error probing backends: {e}")
    print(f"  cuda_available(): {backends.cuda_available()}")
    if shutil.which("nvidia-smi"):
        os.system("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/  GPU: /'")

    print("\nwhisper.cpp:")
    for line in _whispercpp_lines(cfg):
        print(line)

    print("\nparakeet:")
    for line in _parakeet_lines(cfg):
        print(line)

    print("\nlanguage resolution:")
    for line in _language_lines(cfg):
        print(line)

    print("\nchat/terminal formatting:")
    for line in _formatting_lines(cfg):
        print(line)

    print("\ninsertion hardening:")
    for line in _insertion_lines(cfg):
        print(line)

    print(f"\ncontrol socket: {paths.socket_path()} "
          f"({'alive' if paths.socket_path().exists() else 'daemon not running'})")
    print("\n".join(_hotkey_grab_line()))
    if _gtk_available():
        print("settings app: GTK 4 + libadwaita OK (`sayit-ermano app`)")
    else:
        print("settings app: GTK 4 / libadwaita missing - install with\n"
              "  apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
        ok = False

    print("\nresult:", "ready" if ok else "see warnings above")
    return 0 if ok else 1
