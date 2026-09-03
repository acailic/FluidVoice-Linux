"""FluidVoiceLinux command line interface."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from . import __version__, doctor as doctor_mod, paths
from .config import load_config, write_template

# Above this size we warn: v1 has no chunked uploads, so huge inputs are slow.
LARGE_INPUT_BYTES = 25 * 1024 * 1024


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fluidvoice",
        description="FluidVoice for Linux - local voice dictation with AI polish")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("daemon", help="run the dictation daemon (foreground)")
    p.add_argument("--no-hotkey", action="store_true",
                   help="skip the X11 global hotkey (use `fluidvoice toggle` instead)")
    p.add_argument("--no-sounds", action="store_true", help="disable start/stop sounds")
    p.add_argument("--config", type=Path, help="alternative config file")

    for name, help_ in [("toggle", "start/stop a recording"),
                        ("cancel", "cancel the running recording (no transcription)"),
                        ("status", "daemon status"),
                        ("paste-last", "re-type the most recent transcription")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--json", action="store_true", help="raw JSON output")

    p = sub.add_parser("transcribe", help="one-shot transcription of an audio file")
    p.add_argument("file", type=Path,
                   help="audio file (wav/flac/mp3/opus/oga/ogg/m4a/aac/wma/aiff/webm)")
    p.add_argument("--no-process", action="store_true",
                   help="skip filler/punctuation post-processing")
    p.add_argument("--ai", action="store_true", help="also run AI polish")
    p.add_argument("--json", action="store_true",
                   help="print structured JSON {text, language, duration_s, segments} "
                        "instead of plain text")
    p.add_argument("--out", type=Path, metavar="PATH",
                   help="write the result to PATH instead of stdout (plain text, "
                        "or JSON with --json)")
    p.add_argument("--config", type=Path, help="alternative config file")

    p = sub.add_parser("history", help="show recent transcriptions")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--export", type=Path, metavar="PATH.zip",
                   help="write history + retained audio to a zip")

    p = sub.add_parser("config", help="show/init the config file")
    p.add_argument("action", nargs="?", default="path", choices=["path", "init", "print"])

    p = sub.add_parser("settings",
                       help="open the native Settings window (alias of `app --open settings`)")
    p = sub.add_parser("app", help="open the native GTK app (History/Settings)")
    p.add_argument("--open", choices=["history", "settings"], default="history",
                   help="window to raise (default: history)")
    p.add_argument("--onboard", action="store_true",
                   help="run the first-run onboarding flow")
    sub.add_parser("doctor", help="environment check")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    if args.cmd == "daemon":
        from .daemon import Daemon
        cfg = load_config(args.config)
        Daemon(cfg, use_hotkey=not args.no_hotkey,
               use_sounds=not args.no_sounds).run()
        return 0

    if args.cmd in ("toggle", "cancel", "status", "paste-last"):
        from . import control
        try:
            resp = control.request(args.cmd)
        except control.ControlError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(resp))
        else:
            print(_describe(resp))
        return 0 if resp.get("ok") else 1

    if args.cmd == "transcribe":
        from . import backends
        from .ai.client import AIClient
        from .audio_utils import SUPPORTED_AUDIO_EXTS, AudioFormatError, ensure_wav
        from .processing import post_process
        if not args.file.exists():
            print(f"error: file not found: {args.file}", file=sys.stderr)
            return 1
        if args.file.stat().st_size > LARGE_INPUT_BYTES:
            size_mb = args.file.stat().st_size / 1e6
            print(f"warning: input is {size_mb:.1f} MB; transcription is not "
                  "chunked in v1 and may be slow/memory-heavy. Shrinking first "
                  f"usually helps: ffmpeg -i {args.file} -ar 16000 -ac 1 out.wav",
                  file=sys.stderr)
        cfg = load_config(args.config)
        backend = backends.load_backend(cfg)
        if args.file.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
            print(f"note: '{args.file.suffix}' is not a verified format - trying "
                  "anyway (ffmpeg fallback when needed)", file=sys.stderr)
        audio, converted_dir = args.file, None
        try:
            try:
                audio = ensure_wav(args.file, force=backend.name == "whisper.cpp")
            except AudioFormatError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            if audio != args.file:
                converted_dir = audio.parent
            result = backend.transcribe(audio, language=cfg["general"]["language"])
        finally:
            if converted_dir is not None:
                shutil.rmtree(converted_dir, ignore_errors=True)
        text = result["text"]
        if not args.no_process:
            text = post_process(text, cfg)
        if args.ai and cfg["ai"].get("enabled"):
            text = AIClient(cfg).polish(text)
        elif args.ai:
            print("(ai.enabled=false in config; raw transcription only)", file=sys.stderr)
        if args.json:
            payload = {"text": text,  # final text (post-processed/AI if on)
                       "language": result.get("language"),
                       # null for torch/whisper.cpp; [] when backend exposes none
                       "duration_s": result.get("duration"),
                       # raw per-segment text, not post-processed
                       "segments": result.get("segments", [])}
            out_text = json.dumps(payload, indent=2, ensure_ascii=False)
        else:
            out_text = text
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(out_text + "\n", encoding="utf-8")
            print(f"wrote {args.out}", file=sys.stderr)  # stderr keeps stdout clean
        else:
            print(out_text)
        return 0

    if args.cmd == "history":
        from . import history
        if args.export:
            def _note(m):
                print(m, file=sys.stderr)
            try:
                n = history.export_zip(args.export, on_note=_note)
            except OSError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            print(f"exported {n} entries to {args.export}")
            return 0
        for entry in history.tail(args.n):
            ts = entry.get("ts")
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "?"
            ai = " [AI]" if entry.get("ai") else ""
            print(f"{when}{ai}: {entry.get('text', '')}")
        return 0

    if args.cmd == "config":
        if args.action == "init":
            path = write_template()
            print(f"wrote {path}")
        elif args.action == "print":
            print(paths.config_file().read_text() if paths.config_file().exists()
                  else "(no config file - defaults in use; run `fluidvoice config init`)")
        else:
            print(paths.config_file())
        return 0

    if args.cmd == "settings":
        # Kept for the .desktop entry (Exec=fluidvoice settings): opens the
        # native window now that the web UI is retired.
        from .gtkui.application import run as run_app
        return run_app(["--open", "settings"])

    if args.cmd == "app":
        from .gtkui.application import run as run_app
        return run_app(["--open", args.open] + (["--onboard"] if args.onboard else []))

    if args.cmd == "doctor":
        return doctor_mod.run()

    return 0


def _describe(resp: dict) -> str:
    if "recording" in resp:
        state = "recording" if resp["recording"] else "stopped"
        text = f"{state}" + (" (cancelled)" if resp.get("cancelled") else "")
        if "today" in resp:
            from . import history
            text += "\ntoday: " + history.format_today(resp["today"])
        return text
    return json.dumps(resp)


if __name__ == "__main__":
    raise SystemExit(main())
