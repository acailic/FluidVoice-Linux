"""Suite-wide process-state guards.

Loaded before any test module is imported (pytest imports conftest first),
which is exactly what the Pillow warm-up below needs — and what the XDG
isolation below needs too: every paths.py resolution must already point
into the session tmp root by the time any test module runs.
"""
from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest


def _warm_pillow_freetype() -> None:
    """Load one Pillow truetype face before GTK/Pango can render text.

    Pillow wheels vendor their own FreeType/HarfBuzz (pillow.libs). If the
    first face load happens AFTER Pango has rendered in this process, every
    later Pillow text measurement returns garbage (negative or huge
    advances) - pill widths collapse and test_overlay renders
    hundred-megapixel canvases, but only when a gtkui test ran first, so it
    reads as an unexplained order dependency. Loading any face (and walking
    one glyph advance) before the first test pins the vendored library into
    a good state for the whole session. No-op when no system font exists
    (headless CI): overlay falls back to load_default there and no gtkui
    test runs without a display anyway.
    """
    try:
        from fluidvoice.overlay import _load_font

        font = _load_font(13, bold=True)
        if font is not None:
            font.getlength("warm")
    except Exception:
        pass  # measurement guards must never break collection


_warm_pillow_freetype()


# ---------------------------------------------------------------------------
# Session XDG isolation — the suite must NEVER write into the live data dir.
# ---------------------------------------------------------------------------
# History of the bug this guards against: command-mode tests built real
# CommandSessions whose default history appender fell through to
# history.append(), and paths.py resolved history.jsonl under
# ~/.local/share/sayit-ermano — 768 test rows polluted the production file
# (~192 suite runs x 4 rows), inflating `status` today-counts, the History
# window, exports and dictionary learning.
#
# paths.py reads the XDG env vars lazily on every call and nothing in the
# package caches a resolved path at import, so setting the env HERE (conftest
# import time, before any test module) is a complete seam — no production
# code change needed. Import-time (not a session fixture) so module-level
# path use in test modules and any spawned subprocess env are covered too.
# Hard assignment, not setdefault: a leaked outer XDG var must still lose.
# Per-test monkeypatch.setenv/monkeypatch.setattr overrides keep winning
# (they run later). tests/integration/conftest.py isolates its own env per
# test on top of this; it is untouched.
from fluidvoice import paths as _paths

# Snapshot the REAL resolved paths BEFORE the override: these are the
# production locations the guard below watches (and what
# tests/test_conftest_isolation.py asserts stay untouched).
REAL_HISTORY_FILE = _paths.history_file()
REAL_SUGGESTIONS_FILE = _paths.dictionary_suggestions_file()
REAL_CONFIG_FILE = _paths.config_file()

TEST_XDG_ROOT = Path(tempfile.mkdtemp(prefix="sayit-test-xdg-"))
os.environ["XDG_DATA_HOME"] = str(TEST_XDG_ROOT / "data")
os.environ["XDG_CONFIG_HOME"] = str(TEST_XDG_ROOT / "config")
os.environ["XDG_CACHE_HOME"] = str(TEST_XDG_ROOT / "cache")
atexit.register(shutil.rmtree, TEST_XDG_ROOT, ignore_errors=True)


def _fingerprint(p: Path):
    """None when the file is missing, else (mtime_ns, size, sha256) —
    catches appends (size/mtime) AND size-preserving rewrites (hash)."""
    try:
        data = p.read_bytes()
    except OSError:
        return None
    return (p.stat().st_mtime_ns, p.stat().st_size,
            hashlib.sha256(data).hexdigest())


_GUARDED_REAL_FILES = {
    "history": REAL_HISTORY_FILE,
    "suggestions": REAL_SUGGESTIONS_FILE,
    "config": REAL_CONFIG_FILE,
}


@pytest.fixture(scope="session", autouse=True)
def _real_data_untouched():
    """Tripwire: the whole suite must leave the real data/config files
    byte-identical (a missing file must stay missing — non-creation).
    Failing here raises during session teardown, so pytest reports it as a
    session ERROR even when every test passed — intended: a green run that
    mutated production is exactly the failure this exists to catch."""
    before = {name: _fingerprint(p) for name, p in _GUARDED_REAL_FILES.items()}
    yield
    after = {name: _fingerprint(p) for name, p in _GUARDED_REAL_FILES.items()}
    for name, was in before.items():
        assert after[name] == was, (
            f"suite wrote to the real {name} file "
            f"({_GUARDED_REAL_FILES[name]}): {was} -> {after[name]}")
