#!/usr/bin/env bash
# FluidVoiceLinux installer (Pop!_OS / Ubuntu / Debian, X11)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

echo "== 1/5 system packages (sudo) =="
sudo apt-get update -qq
sudo apt-get install -y python3-venv python3-pip pipewire-audio-utils xdotool xclip \
    libnotify-bin pulseaudio-utils

echo "== 2/5 python venv (reuses system CUDA torch if present) =="
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -U pip -q
.venv/bin/pip install -e . -q

echo "== 3/5 config =="
[ -f ~/.config/fluidvoice/config.toml ] || .venv/bin/fluidvoice config init

echo "== 4/5 systemd user unit (path + DISPLAY baked in) =="
UNIT_DIR=~/.config/systemd/user
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/fluidvoice.service" <<UNIT
[Unit]
Description=FluidVoiceLinux dictation daemon
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
Environment=DISPLAY=${DISPLAY:-:0}
Environment=XAUTHORITY=${XAUTHORITY:-$HOME/.Xauthority}
ExecStart=$REPO_DIR/.venv/bin/fluidvoice daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now fluidvoice.service

echo "== 5/5 verify =="
.venv/bin/fluidvoice doctor
systemctl --user --no-pager status fluidvoice.service | head -5 || true

cat <<'NOTE'

Done. The daemon runs as a systemd user service tied to your graphical
session (starts at login, stops at logout).
  Start/stop:  systemctl --user start|stop fluidvoice
  Logs:        journalctl --user -u fluidvoice -f
  Settings UI: $REPO_DIR/.venv/bin/fluidvoice settings
  Hotkey:      Right Ctrl (tap to start, tap again to type)

NOTE
