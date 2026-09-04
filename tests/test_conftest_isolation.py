"""Regression guard: the suite must never write to the real (live) data
files — history.jsonl above all.

This is the test module that would have caught the leak measured
2026-09-04: 768 of 782 entries in ~/.local/share/sayit-ermano/history.jsonl
were command-mode TEST rows ("true 1"/"true 2"/"exit 3"/"echo hi", purpose
"fail"/"p", duration_ms 0-1) written by tests/test_command.py building real
CommandSessions whose default history appender fell through to
history.append(). tests/conftest.py now redirects every XDG resolution into
a session tmp root at import time; these tests pin that redirect in place
and re-run the exact leak path against it.
"""
from __future__ import annotations

import copy
import os

from fluidvoice import command as cm
from fluidvoice import history, paths
from fluidvoice.config import DEFAULTS
from tests.conftest import REAL_HISTORY_FILE, TEST_XDG_ROOT, _fingerprint
from tests.test_command import StubAIClient, ai_ready


class TestSessionIsolation:
    def test_env_points_into_session_tmp(self):
        assert os.environ["XDG_DATA_HOME"].startswith(str(TEST_XDG_ROOT))
        assert os.environ["XDG_CONFIG_HOME"].startswith(str(TEST_XDG_ROOT))
        assert paths.history_file().is_relative_to(TEST_XDG_ROOT)
        assert paths.audio_dir().is_relative_to(TEST_XDG_ROOT)
        assert paths.dictionary_suggestions_file().is_relative_to(TEST_XDG_ROOT)
        assert paths.config_file().is_relative_to(TEST_XDG_ROOT)
        assert paths.history_file() != REAL_HISTORY_FILE

    def test_real_paths_captured_before_override(self):
        # Sanity that the conftest snapshot ran BEFORE the env override:
        # the guarded "real" path must be the production one, not under tmp.
        assert not REAL_HISTORY_FILE.is_relative_to(TEST_XDG_ROOT)

    def test_append_lands_in_tmp(self):
        before = _fingerprint(REAL_HISTORY_FILE)
        history.append({"ts": 123.0, "text": "isolation probe"})
        hpath = paths.history_file()
        assert hpath.is_relative_to(TEST_XDG_ROOT) and hpath.exists()
        assert _fingerprint(REAL_HISTORY_FILE) == before

    def test_command_session_default_appender_isolated(self):
        """The exact leak path, kept as a canary: CommandSession with NO
        injected history_appender falls through to history_mod.append
        (command.py _write_history). Before the conftest isolation this
        wrote "true 1" rows straight into the REAL history file; now the
        row must land under the session tmp root and the real file's
        fingerprint (mtime_ns/size/sha256) must be unchanged."""
        cfg = ai_ready(copy.deepcopy(DEFAULTS))

        def runner(cmd, cwd=None, timeout=None):
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="ok", duration_ms=0)

        before = _fingerprint(REAL_HISTORY_FILE)
        from tests.test_command import done_reply, reply
        s = cm.CommandSession(
            cfg,
            client=StubAIClient(
                [reply(("true 1", "p")), done_reply("ok")]),
            runner=runner)
        assert s.start("x") is not None
        s.confirm()
        assert s.finished and not s.cancelled

        hpath = paths.history_file()
        cmds = [e.get("command") for e in history.read_all()
                if e.get("mode") == "command"]
        assert "true 1" in cmds
        assert hpath.is_relative_to(TEST_XDG_ROOT)
        assert _fingerprint(REAL_HISTORY_FILE) == before
