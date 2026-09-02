#!/usr/bin/env bash
# FluidVoiceLinux one-shot installer.
#
#   curl -fsSL https://raw.githubusercontent.com/acailic/FluidVoice-Linux/linux/scripts/install-one-shot.sh | bash
#
# Downloads the newest release .deb and installs it (launcher entry, login
# autostart, `fluidvoice` CLI). Ubuntu / Pop!_OS / Debian on x86-64, X11.
#
# Options:
#   bash install-one-shot.sh ./local.deb   install a specific .deb
#   bash install-one-shot.sh --uninstall   remove the package
#   DRY_RUN=1 ...                          download+verify only
set -euo pipefail

REPO="acailic/FluidVoice-Linux"
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- uninstall mode ---------------------------------------------------------
if [ "${1:-}" = "--uninstall" ]; then
    say "Removing FluidVoiceLinux..."
    sudo apt remove -y fluidvoice-linux
    say "Removed. (config kept at ~/.config/fluidvoice)"
    exit 0
fi

# --- environment checks -----------------------------------------------------
command -v curl >/dev/null || die "curl is required"
command -v apt >/dev/null || die "this installer needs apt (Ubuntu/Pop!_OS/Debian)"
[ "$(dpkg --print-architecture 2>/dev/null)" = "amd64" ] \
    || die "only amd64 packages are published for now (you: $(dpkg --print-architecture 2>/dev/null || echo '?'))"

# --- locate the .deb --------------------------------------------------------
if [ -n "${1:-}" ] && [ -f "$1" ]; then
    DEB="$1"
    say "Using local package: $DEB"
else
    say "Looking up the latest release..."
    # /releases/latest works via the API even though the web redirect does not
    # on forks; fall back to the list endpoint just in case.
    RELEASE_JSON="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        || curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=1" \
        | sed -n 's/^.\{0,1\}\[/[/p')"  # list endpoint: keep the array
    URL="$(printf '%s' "$RELEASE_JSON" \
        | grep -o '"browser_download_url": *"[^"]*_amd64\.deb"' \
        | head -1 | sed 's/.*"\(https[^"]*\)"/\1/')" \
        || URL=""
    [ -n "$URL" ] || die "no amd64 .deb found in the latest release"
    say "Downloading $URL"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    DEB="$TMP/$(basename "$URL")"
    curl -fL --progress-bar -o "$DEB" "$URL"
    # sanity: a real package is tens of MB; an error page is a few KB
    SIZE="$(stat -c%s "$DEB")"
    [ "$SIZE" -gt 10000000 ] || die "downloaded file looks wrong (${SIZE} bytes) - not installing it"
    say "Downloaded $(du -h "$DEB" | cut -f1)"
fi

# --- install -----------------------------------------------------------------
if [ "${DRY_RUN:-0}" = "1" ]; then
    say "DRY_RUN=1: package ready, skipping install ($DEB)"
else
    say "Installing (sudo will ask for your password)..."
    sudo apt install -y "$DEB"
    cat <<'NOTE'

  FluidVoice installed! One more thing: log out and back in once so the
  daemon autostarts and the launcher entry appears.

  Then:
    - press Right Ctrl, speak, press Right Ctrl again -> text is typed
    - "FluidVoice" in your app launcher opens the settings UI
      (model picker, AI polish, history) - or run: fluidvoice settings
    - fluidvoice doctor     check everything is healthy
    - fluidvoice --help     all commands

NOTE
fi
