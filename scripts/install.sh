#!/usr/bin/env bash
# FluidVoiceLinux installer (Pop!_OS / Ubuntu / Debian, X11)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/4 system packages (sudo) =="
sudo apt-get update -qq
sudo apt-get install -y python3-venv pipewire-audio-utils xdotool xclip \
    libnotify-bin pulseaudio-utils

echo "== 2/4 python venv (reuses system CUDA torch if present) =="
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -U pip -q
.venv/bin/pip install -e . -q
.venv/bin/pip install pytest -q

echo "== 3/4 config =="
[ -f ~/.config/fluidvoice/config.toml ] || .venv/bin/fluidvoice config init

echo "== 4/4 verify =="
.venv/bin/fluidvoice doctor

cat <<'NOTE'

Done. Next steps:
  1. Start the daemon:   ~/.local/bin/fluidvoice daemon   (or the systemd unit)
  2. Press Right Ctrl (default hotkey), speak, press again -> text is typed.
  3. Optional AI polish:  set [ai] enabled=true + model in the config
     (works with Ollama: `ollama pull qwen3:8b`).

NOTE
