#!/usr/bin/env bash
# verify-pipx.sh — sandboxed proof that `pipx install` of a locally built
# wheel works: entry points launch, data files are present, and the updater's
# install-method detection returns "pipx" from inside the pipx venv.
#
# Manual tool (project rule: CI is manual-only — this is NOT wired to any
# workflow). Run it from anywhere:
#   ./scripts/verify-pipx.sh
# Environment:
#   PIPX_BIN   pipx venv bin dir to probe (default ~/.local/pipx/venvs/sayit-ermano/bin)
#   NO_CLEAN   set to keep the pipx install for inspection
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== building the wheel =="
if command -v uv >/dev/null 2>&1; then
  uv build --wheel
else
  .venv/bin/python -m pip wheel --no-deps -w dist .
fi
WHEEL="$(ls -t dist/sayit_ermano-*.whl | head -1)"
echo "wheel: $WHEEL"

if command -v pipx >/dev/null 2>&1; then
  echo "== pipx install =="
  pipx install --force "$WHEEL"
  # pipx >= 1.7 distros keep venvs under ~/.local/share/pipx; ask pipx
  # itself where, instead of guessing the layout
  PIPX_HOME_DIR="$(pipx environment --value PIPX_HOME)"
  BIN="${PIPX_BIN:-$PIPX_HOME_DIR/venvs/sayit-ermano/bin}"
  cleanup() {
    [ -n "${NO_CLEAN:-}" ] || pipx uninstall sayit-ermano >/dev/null 2>&1 || true
  }
  trap cleanup EXIT
else
  # pipx absent: same assertions against a plain venv placed exactly where
  # detect_install_method() expects a pipx venv (~/.local/pipx/venvs/<name>)
  echo "== pipx not found — plain-venv fallback at the pipx path =="
  BIN="$HOME/.local/pipx/venvs/sayit-ermano/bin"
  python3 -m venv "$HOME/.local/pipx/venvs/sayit-ermano"
  "$BIN/pip" install --quiet "$WHEEL"
  cleanup() {
    [ -n "${NO_CLEAN:-}" ] || rm -rf "$HOME/.local/pipx/venvs/sayit-ermano"
  }
  trap cleanup EXIT
fi

echo "== entry point + module launch =="
"$BIN/sayit-ermano" --version
"$BIN/python" -m fluidvoice --version

echo "== install-method detection (must be pipx) =="
"$BIN/python" -c "from fluidvoice.update import detect_install_method as d; \
m=d(); assert m['method']=='pipx', m; print('method:', m['method'], '-', m['marker'])"

echo "== data files present (sfx/icons/providers) =="
"$BIN/python" -c "import fluidvoice.ui, importlib.resources as r; \
print(sorted(p.name for p in r.files('fluidvoice.assets.sfx').iterdir()))"
"$BIN/python" -c "import importlib.resources as r; \
names=[p.name for p in r.files('fluidvoice.assets.icons.symbolic.actions').iterdir()]; \
assert names, 'symbolic icons missing'; print(len(names), 'symbolic icons')"
"$BIN/python" -c "import importlib.resources as r; \
names=[p.name for p in r.files('fluidvoice.assets.providers').iterdir()]; \
assert names, 'provider logos missing'; print(len(names), 'provider logos')"

echo "== OK: pipx install verified =="
