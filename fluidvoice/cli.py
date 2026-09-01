"""FluidVoiceLinux command line interface."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, doctor as doctor_mod, paths
from .config import load_config, write_template


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
                        ("status", "daemon status")]:
        p = sub.add_parser(name, help=help_)
        p.add_argument("--json", action="store_true", help="raw JSON output")

    p = sub.add_parser("transcribe", help="one-shot transcription of an audio file")
    p.add_argument("file", type=Path, help="audio file (wav/flac/mp3/...)")
    p.add_argument("--no-process", action="store_true",
                   help="skip filler/punctuation post-processing")
    p.add_argument("--ai", action="store_true", help="also run AI polish")
    p.add_argument("--config", type=Path, help="alternative config file")

    p = sub.add_parser("history", help="show recent transcriptions")
    p.add_argument("-n", type=int, default=10)

    p = sub.add_parser("config", help="show/init the config file")
    p.add_argument("action", nargs="?", default="path", choices=["path", "init", "print"])

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

    if args.cmd in ("toggle", "cancel", "status"):
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
        from .processing import post_process
        cfg = load_config(args.config)
        backend = backends.load_backend(cfg)
        result = backend.transcribe(args.file, language=cfg["general"]["language"])
        text = result["text"]
        if not args.no_process:
            text = post_process(text, cfg)
        if args.ai and cfg["ai"].get("enabled"):
            text = AIClient(cfg).polish(text)
        elif args.ai:
            print("(ai.enabled=false in config; raw transcription only)", file=sys.stderr)
        print(text)
        return 0

    if args.cmd == "history":
        from . import history
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

    if args.cmd == "doctor":
        return doctor_mod.run()

    return 0


def _describe(resp: dict) -> str:
    if "recording" in resp:
        state = "recording" if resp["recording"] else "stopped"
        return f"{state}" + (" (cancelled)" if resp.get("cancelled") else "")
    return json.dumps(resp)


if __name__ == "__main__":
    raise SystemExit(main())
