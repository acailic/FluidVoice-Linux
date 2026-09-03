#!/usr/bin/env bash
# FluidVoiceLinux one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/acailic/FluidVoice-Linux/linux/scripts/install-one-shot.sh | bash
#
# DEFAULT (no sudo): installs into your home directory
#   ~/.local/share/fluidvoice-linux/venv     bundled runtime
#   ~/.local/bin/fluidvoice                  CLI (must be on PATH)
#   ~/.local/share/applications + icons      launcher entry
#   ~/.config/autostart/                     daemon at login
#   ~/.config/systemd/user/fluidvoice.service  (shadows any system unit)
# A system-wide .deb install remains available:  bash install-one-shot.sh --system
#
# Options:
#   bash install-one-shot.sh ./local.deb    install a specific .deb (user layout)
#   bash install-one-shot.sh --system       old system-wide path (sudo apt)
#   bash install-one-shot.sh --uninstall    remove the user installation
#   DRY_RUN=1 ...                           download+verify only
set -euo pipefail

REPO="acailic/FluidVoice-Linux"
BIN="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/fluidvoice-linux"
MODE="user"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "${1:-}" = "--system" ] && { MODE="system"; shift; }
if [ "${1:-}" = "--uninstall" ]; then
    say "Removing the user installation..."
    systemctl --user disable --now fluidvoice.service 2>/dev/null || true
    pkill -f "$APP_DIR/venv/bin/python -m fluidvoice" 2>/dev/null || true
    rm -rf "$APP_DIR" "$BIN/fluidvoice" \
        "$HOME/.local/share/applications/fluidvoice-linux.desktop" \
        "$HOME/.config/autostart/fluidvoice-linux.desktop" \
        "$HOME/.config/systemd/user/fluidvoice.service"
    systemctl --user daemon-reload 2>/dev/null || true
    say "Removed. (config kept at ~/.config/fluidvoice)"
    say "A system-wide .deb, if present, is separate: sudo apt remove fluidvoice-linux"
    exit 0
fi

command -v curl >/dev/null || die "curl is required"
[ "$(dpkg --print-architecture 2>/dev/null)" = "amd64" ] \
    || die "only amd64 packages are published for now (you: $(dpkg --print-architecture 2>/dev/null || echo '?'))"

# --- locate the .deb --------------------------------------------------------
if [ -n "${1:-}" ] && [ -f "$1" ]; then
    DEB="$1"
    say "Using local package: $DEB"
else
    say "Looking up the latest release..."
    RELEASE_JSON="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        || curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=1" \
        | sed -n 's/^.\{0,1\}\[/[/p')"
    URL="$(printf '%s' "$RELEASE_JSON" \
        | grep -o '"browser_download_url": *"[^"]*_amd64\.deb"' \
        | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')" \
        || URL=""
    [ -n "$URL" ] || die "no amd64 .deb found in the latest release"
    say "Downloading $URL"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    DEB="$TMP/$(basename "$URL")"
    curl -fL --progress-bar -o "$DEB" "$URL"
    chmod 755 "$TMP"; chmod 644 "$DEB"   # let apt's sandbox read it too
    SIZE="$(stat -c%s "$DEB")"
    [ "$SIZE" -gt 10000000 ] || die "downloaded file looks wrong (${SIZE} bytes) - not installing it"
    say "Downloaded $(du -h "$DEB" | cut -f1)"
fi

# --- optional sudo step: system dependencies --------------------------------
# Only reached when something the app needs at runtime is missing; everything
# else in this script runs entirely as your user.
MISSING=""
for pkg in python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 xdotool xclip libnotify-bin; do
    dpkg -s "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done
command -v pw-record >/dev/null 2>&1 || MISSING="$MISSING pipewire-audio"
if [ -n "$MISSING" ]; then
    warn "missing system packages:$MISSING"
    printf 'Install them now with sudo? [y/N] '
    read -r answer
    if [ "${answer:-n}" = "y" ] || [ "${answer:-n}" = "Y" ]; then
        # shellcheck disable=SC2086
        sudo apt install -y $MISSING
    else
        say "Skipping. The app still installs; install those packages later:"
        say "  sudo apt install -$MISSING"
    fi
fi

if [ "$MODE" = "system" ]; then
    say "Installing system-wide (sudo will ask for your password)..."
    sudo apt install -y "$DEB"
    cat <<'NOTE'

  FluidVoice installed system-wide! Log out and back in once so the daemon
  autostarts and the launcher entry appear.
  (Upgrading? The daemon restarts itself automatically - just close and
  reopen the settings window if you had it open.)

    - press Right Ctrl, speak, press Right Ctrl again -> text is typed
    - "FluidVoice" in your app launcher opens the settings UI
    - fluidvoice doctor     check everything is healthy

NOTE
    exit 0
fi

# --- user-space install (no sudo) --------------------------------------------
if [ "${DRY_RUN:-0}" = "1" ]; then
    say "DRY_RUN=1: package ready, skipping install ($DEB)"
    exit 0
fi
say "Installing into your home directory (no sudo)..."
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
dpkg-deb -x "$DEB" "$STAGE"
[ -d "$STAGE/opt/fluidvoice-linux/venv" ] || die "unexpected package layout"

# stop whatever daemon is running before its files move underneath it
systemctl --user stop fluidvoice.service 2>/dev/null || true
pkill -f '/opt/fluidvoice-linux/.*/python -m fluidvoice daemon' 2>/dev/null || true
pkill -f "$APP_DIR/venv/bin/python -m fluidvoice daemon" 2>/dev/null || true
sleep 1

mkdir -p "$APP_DIR" "$BIN" \
    "$HOME/.local/share/applications" "$HOME/.local/share/icons" \
    "$HOME/.config/autostart" "$HOME/.config/systemd/user"
rm -rf "$APP_DIR/venv"
cp -a "$STAGE/opt/fluidvoice-linux/venv" "$APP_DIR/venv"

cat > "$BIN/fluidvoice" <<WRAP
#!/bin/sh
# FluidVoiceLinux user launcher (keeps the session environment intact)
exec "$APP_DIR/venv/bin/python" -m fluidvoice "\$@"
WRAP
chmod 755 "$BIN/fluidvoice"

sed "s|^Exec=/usr/bin/fluidvoice|Exec=$BIN/fluidvoice|" \
    "$STAGE/usr/share/applications/fluidvoice-linux.desktop" \
    > "$HOME/.local/share/applications/fluidvoice-linux.desktop"
sed "s|^Exec=/usr/bin/fluidvoice|Exec=$BIN/fluidvoice|" \
    "$STAGE/etc/xdg/autostart/fluidvoice-linux.desktop" \
    > "$HOME/.config/autostart/fluidvoice-linux.desktop"
cp -a "$STAGE/usr/share/icons/hicolor/." "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

cat > "$HOME/.config/systemd/user/fluidvoice.service" <<UNIT
[Unit]
Description=FluidVoiceLinux dictation daemon (user install)
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=$BIN/fluidvoice daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
UNIT
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable fluidvoice.service 2>/dev/null || true
systemctl --user restart fluidvoice.service 2>/dev/null || true
systemctl --user start fluidvoice.service 2>/dev/null || true

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) warn "$BIN is not on your PATH - add it:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc" ;;
esac
if dpkg -s fluidvoice-linux >/dev/null 2>&1; then
    warn "a system-wide .deb (fluidvoice-linux) is still installed."
    warn "The user install shadows it (same systemd unit name); to drop the"
    warn "duplicate entirely:  sudo apt remove fluidvoice-linux"
fi

if systemctl --user is-active --quiet fluidvoice.service 2>/dev/null; then
    say "daemon restarted on the new version - no logout needed"
else
    say "daemon will start at next login (start now:  systemctl --user start fluidvoice)"
fi
cat <<'NOTE'

  FluidVoice installed (user-space, no sudo)!

    - press Right Ctrl, speak, press Right Ctrl again -> text is typed
    - "FluidVoice" in your app launcher opens the settings UI
      (model picker, AI polish, history) - or run: fluidvoice settings
    - fluidvoice doctor     check everything is healthy
    - fluidvoice --help     all commands

NOTE
