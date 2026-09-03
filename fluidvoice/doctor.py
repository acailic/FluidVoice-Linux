"""`fluidvoice doctor` - environment report."""
from __future__ import annotations

import os
import shutil

from . import __version__, backends, paths


def _gtk_available() -> bool:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
        return True
    except (ImportError, ValueError):
        return False


def run() -> int:
    print(f"FluidVoiceLinux v{__version__} doctor\n")
    ok = True

    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    print(f"session: {session}  DISPLAY={os.environ.get('DISPLAY', '-')} "
          f"WAYLAND_DISPLAY={os.environ.get('WAYLAND_DISPLAY', '-')}")
    if session == "x11":
        print("  X11: full experience (global hotkey + xdotool typing)")
    elif session == "wayland":
        print("  Wayland: DE-shortcut -> `fluidvoice toggle` works; typing needs "
              "ydotool/wtype (see README)")
        ok = False

    print(f"\nconfig: {paths.config_file()} ({'exists' if paths.config_file().exists() else 'not created yet - defaults in use'})")
    print(f"history: {paths.history_file()}")
    print(f"models cache: {paths.models_dir()}")

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

    print(f"\ncontrol socket: {paths.socket_path()} "
          f"({'alive' if paths.socket_path().exists() else 'daemon not running'})")
    if _gtk_available():
        print("settings app: GTK 4 + libadwaita OK (`fluidvoice app`)")
    else:
        print("settings app: GTK 4 / libadwaita missing - install with\n"
              "  apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
        ok = False

    print("\nresult:", "ready" if ok else "see warnings above")
    return 0 if ok else 1
