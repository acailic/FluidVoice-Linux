"""Command mode: strict-JSON protocol, session loop, run_shell, readiness.

The daemon wiring tests (TestDaemonCommandMode / TestPipelineCommandMode)
live here too, importing the daemon-test fixtures like test_extra_formats.
"""
from __future__ import annotations

import json
import time

import pytest

from fluidvoice import command as cm
from fluidvoice.ai.client import AIError
from tests.test_daemon import StubBackend, StubRecorder, make_wav, quiet_ui, cfg


class StubAIClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_messages(self, messages, temperature=None):
        self.calls.append([dict(m) for m in messages])  # snapshot
        if not self.replies:
            raise AssertionError("unexpected extra LLM call")
        return self.replies.pop(0)


def ai_ready(cfg):
    cfg["ai"]["enabled"] = True
    cfg["ai"]["base_url"] = "http://localhost:11434/v1"
    cfg["ai"]["model"] = "qwen3:8b"
    return cfg


def reply(*specs, done=False, summary=None):
    """Build a strict-JSON tool_calls reply. Each spec is a tuple
    (command, purpose=None, workingDirectory=None)."""
    calls = []
    for spec in specs:
        args = {"command": spec[0]}
        if len(spec) > 1 and spec[1] is not None:
            args["purpose"] = spec[1]
        if len(spec) > 2 and spec[2] is not None:
            args["workingDirectory"] = spec[2]
        calls.append({"id": f"call_{len(calls) + 1}",
                      "name": "execute_terminal_command",
                      "arguments": args})
    obj = {"tool_calls": calls, "done": done}
    if summary is not None:
        obj["summary"] = summary
    return json.dumps(obj)


def done_reply(summary="ok"):
    return reply(done=True, summary=summary)


class TestFences:
    def test_json_fence_stripped(self):
        assert cm.strip_code_fences(
            '```json\n{"command": "ls"}\n```') == '{"command": "ls"}'

    def test_bare_json_unchanged(self):
        assert cm.strip_code_fences('{"command": "ls"}') == '{"command": "ls"}'

    def test_fence_without_language_tag(self):
        assert cm.strip_code_fences(
            '```\n{"a": 1}\n```') == '{"a": 1}'

    def test_fence_with_surrounding_blank_lines(self):
        assert cm.strip_code_fences(
            '\n\n  ```json\n{"a": 1}\n  ```  \n\n') == '{"a": 1}'

    def test_plain_text_unchanged(self):
        assert cm.strip_code_fences("just words") == "just words"


class TestParseReply:
    def test_single_call_parses_with_validated_args(self):
        r = cm.parse_reply(reply(("ls -la", "list")))
        assert r.kind == "proposal"
        assert len(r.calls) == 1
        call = r.calls[0]
        assert call.name == "execute_terminal_command"
        assert call.command == "ls -la"
        assert call.purpose == "list"
        assert call.working_directory is None
        assert call.id == "call_1"

    def test_multi_call_reply_parses(self):
        r = cm.parse_reply(reply(
            ("ls /var/log", "checking", "/tmp"),
            ("du -sh /var/log", "executing")))
        assert r.kind == "proposal"
        assert [c.command for c in r.calls] == \
            ["ls /var/log", "du -sh /var/log"]
        assert r.calls[0].working_directory == "/tmp"
        assert r.calls[0].purpose == "checking"
        assert r.calls[1].working_directory is None
        assert r.calls[1].id == "call_2"

    def test_working_directory_honored_and_empty_normalized(self):
        r = cm.parse_reply(reply(("pwd", "p", "  ")))
        assert r.calls[0].working_directory is None

    def test_id_generated_when_absent(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command",
             "arguments": {"command": "date"}},
            {"id": "custom", "name": "execute_terminal_command",
             "arguments": {"command": "uptime"}}]})
        r = cm.parse_reply(raw)
        assert r.calls[0].id == "call_1"   # synthesized (upstream :863)
        assert r.calls[1].id == "custom"

    def test_unknown_tool_name_raises_naming_the_tool(self):
        raw = json.dumps({"tool_calls": [
            {"name": "delete_files", "arguments": {"command": "rm x"}}]})
        with pytest.raises(cm.CommandError) as ei:
            cm.parse_reply(raw)
        assert "delete_files" in str(ei.value)
        assert "rm x" in str(ei.value)  # raw text embedded

    def test_missing_command_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command", "arguments": {}}]})
        with pytest.raises(cm.CommandError, match="non-empty"):
            cm.parse_reply(raw)

    def test_empty_command_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command",
             "arguments": {"command": "   "}}]})
        with pytest.raises(cm.CommandError, match="non-empty"):
            cm.parse_reply(raw)

    def test_non_string_command_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command",
             "arguments": {"command": 42}}]})
        with pytest.raises(cm.CommandError, match="non-empty"):
            cm.parse_reply(raw)

    def test_non_object_arguments_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command", "arguments": "ls"}]})
        with pytest.raises(cm.CommandError, match="arguments"):
            cm.parse_reply(raw)

    def test_non_string_working_directory_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command",
             "arguments": {"command": "ls", "workingDirectory": 7}}]})
        with pytest.raises(cm.CommandError, match="workingDirectory"):
            cm.parse_reply(raw)

    def test_non_string_purpose_raises(self):
        raw = json.dumps({"tool_calls": [
            {"name": "execute_terminal_command",
             "arguments": {"command": "ls", "purpose": 3}}]})
        with pytest.raises(cm.CommandError, match="purpose"):
            cm.parse_reply(raw)

    def test_purpose_optional(self):
        r = cm.parse_reply(reply(("date",)))
        assert r.calls[0].purpose is None

    def test_empty_tool_calls_not_done_raises(self):
        with pytest.raises(cm.CommandError, match="could not parse"):
            cm.parse_reply('{"tool_calls": [], "done": false}')

    def test_done_with_summary(self):
        r = cm.parse_reply(done_reply("all good"))
        assert r.kind == "done" and r.summary == "all good"
        assert r.calls is None

    def test_done_without_summary(self):
        r = cm.parse_reply('{"done": true}')
        assert r.kind == "done" and r.summary == "Done."

    def test_prose_wrapped_json_tolerated(self):
        r = cm.parse_reply(
            'Sure! Here you go:\n' + reply(("pwd", "where"))
            + '\nHope that helps.')
        assert r.kind == "proposal" and r.calls[0].command == "pwd"

    def test_garbage_raises_with_raw_text(self):
        with pytest.raises(cm.CommandError) as ei:
            cm.parse_reply("I will just run ls for you")
        assert "I will just run ls for you" in str(ei.value)

    def test_fenced_done_reply(self):
        r = cm.parse_reply('```json\n' + done_reply("done ok") + '\n```')
        assert r.kind == "done" and r.summary == "done ok"

    def test_fenced_multi_call_reply(self):
        r = cm.parse_reply('```json\n'
                           + reply(("ls", "a"), ("pwd", "b")) + '\n```')
        assert len(r.calls) == 2

    def test_think_tags_stripped(self):
        r = cm.parse_reply('<think>reasoning here</think>' + reply(("date",)))
        assert r.kind == "proposal" and r.calls[0].command == "date"


class TestReadiness:
    def test_disabled_ai(self, cfg):
        issue = cm.command_mode_ready(cfg)
        assert issue == "command mode needs [ai] enabled with a model"
        with pytest.raises(cm.CommandError, match="needs \\[ai\\] enabled"):
            cm.CommandSession(cfg).start("x")

    def test_enabled_but_unconfigured(self, cfg):
        cfg["ai"]["enabled"] = True
        assert cm.command_mode_ready(cfg) == \
            "AI enabled but base_url/model not configured"
        with pytest.raises(cm.CommandError, match="not configured"):
            cm.CommandSession(cfg).start("x")

    def test_ready_when_configured(self, cfg):
        assert cm.command_mode_ready(ai_ready(cfg)) is None


class TestSessionLoop:
    def _session(self, cfg, replies, **kw):
        client = StubAIClient(replies)
        return client, cm.CommandSession(cfg, client=client, **kw)

    def test_propose_confirm_execute_done(self, cfg):
        ai_ready(cfg)
        history = []
        client, s = self._session(
            cfg,
            [reply(("echo hello", "say hi")), done_reply("said hello")],
            history_appender=history.append)
        prop = s.start("say hello")
        assert prop is not None and prop.command == "echo hello"
        assert s.pending is prop
        assert s.confirm() is None
        assert s.executed[0].exit_code == 0
        assert "hello" in s.executed[0].output
        assert s.summary == "said hello"
        assert s.finished and not s.cancelled
        assert len(history) == 1
        entry = history[0]
        assert entry["mode"] == "command"
        assert entry["command"] == "echo hello"
        assert "hello" in entry["output"]
        assert entry["text"] == "$ echo hello"

    def test_multi_call_set_one_llm_round_trip(self, cfg):
        """2 calls in one reply: start presents call 1; the first confirm
        executes it and presents call 2 with NO second LLM call; the second
        confirm executes it, then exactly ONE advance runs with a batched
        results message carrying both commands."""
        ai_ready(cfg)
        runs = []

        def runner(cmd, cwd=None, timeout=None):
            runs.append(cmd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output=f"out:{cmd}")

        client, s = self._session(
            cfg,
            [reply(("echo one", "a"), ("echo two", "b")),
             done_reply("both ran")],
            runner=runner)
        prop = s.start("do both")
        assert prop.command == "echo one"
        assert len(client.calls) == 1          # one LLM call so far
        prop2 = s.confirm()
        assert prop2 is not None and prop2.command == "echo two"
        assert len(client.calls) == 1          # no round-trip inside the set
        assert runs == ["echo one"]
        assert s.confirm() is None             # set done -> advance -> done
        assert runs == ["echo one", "echo two"]
        assert len(client.calls) == 2          # exactly one advance
        assert s.summary == "both ran"
        feedback = client.calls[-1][-1]["content"]
        assert feedback.startswith("Command results (JSON):")
        assert '"command": "echo one"' in feedback
        assert '"command": "echo two"' in feedback
        assert '"purpose": "a"' in feedback     # upstream EnhancedCommandResult

    def test_per_call_working_directory_reaches_runner(self, cfg, tmp_path):
        ai_ready(cfg)
        seen = []

        def runner(cmd, cwd=None, timeout=None):
            seen.append((cmd, cwd))
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="")

        client, s = self._session(
            cfg,
            [reply(("pwd", "where", str(tmp_path))), done_reply("ok")],
            runner=runner)
        s.start("where am i")
        s.confirm()
        assert seen[0][1] == tmp_path

    def test_nonexistent_working_directory_falls_back(self, cfg, tmp_path):
        ai_ready(cfg)
        cfg["command"]["working_dir"] = str(tmp_path)
        seen = []

        def runner(cmd, cwd=None, timeout=None):
            seen.append(cwd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="")

        client, s = self._session(
            cfg,
            [reply(("pwd", "where", str(tmp_path / "nope"))),
             done_reply("ok")],
            runner=runner)
        s.start("where")
        s.confirm()
        assert seen[0] == tmp_path             # configured dir, not a crash

    def test_cancel_mid_set_executes_nothing_further(self, cfg):
        ai_ready(cfg)
        runs = []

        def runner(cmd, cwd=None, timeout=None):
            runs.append(cmd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="ok")

        client, s = self._session(
            cfg, [reply(("true 1", "a"), ("true 2", "b"), ("true 3", "c"))],
            runner=runner)
        s.start("x")
        s.confirm()                            # executes call 1, presents 2
        s.cancel()                             # drops calls 2 AND 3
        assert runs == ["true 1"]
        assert s.cancelled and s.finished
        with pytest.raises(cm.CommandError, match="session is over"):
            s.confirm()

    def test_turn_bound(self, cfg):
        ai_ready(cfg)
        cfg["command"]["max_turns"] = 2
        runs = []

        def runner(cmd, cwd=None, timeout=None):
            runs.append(cmd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="ok")

        client, s = self._session(
            cfg,
            [reply(("true 1",)), reply(("true 2",)), reply(("true 3",))],
            runner=runner)
        assert s.start("x") is not None
        assert s.confirm() is not None
        assert s.confirm() is None
        assert s.exhausted and s.finished
        assert "maximum steps" in s.summary.lower()
        assert len(client.calls) == 2
        assert runs == ["true 1", "true 2"]

    def test_two_commands_one_set_within_max_turns(self, cfg):
        """max_turns counts LLM calls, not commands: a 2-call set plus one
        follow-up turn fits inside max_turns=2."""
        ai_ready(cfg)
        cfg["command"]["max_turns"] = 2
        runs = []

        def runner(cmd, cwd=None, timeout=None):
            runs.append(cmd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="ok")

        client, s = self._session(
            cfg,
            [reply(("a1", "a"), ("a2", "b")), done_reply("ok")],
            runner=runner)
        s.start("x")
        assert s.confirm() is not None
        assert s.confirm() is None
        assert s.summary == "ok" and not s.exhausted
        assert runs == ["a1", "a2"]
        assert len(client.calls) == 2

    def test_cancel_executes_nothing(self, cfg):
        ai_ready(cfg)
        history = []
        client, s = self._session(
            cfg, [reply(("rm -rf /", "nope"))],
            history_appender=history.append)
        assert s.start("danger") is not None
        s.cancel()
        assert s.cancelled and s.finished
        assert s.executed == [] and history == []
        with pytest.raises(cm.CommandError, match="session is over"):
            s.confirm()

    def test_failure_feeds_back(self, cfg):
        ai_ready(cfg)
        client, s = self._session(
            cfg,
            [reply(("exit 3", "fail")), done_reply("failed as expected")])
        s.start("make it fail")
        s.confirm()
        assert s.executed[0].success is False
        assert s.executed[0].exit_code == 3
        last = client.calls[-1]
        assert '"exit_code": 3' in last[-1]["content"]
        assert '"success": false' in last[-1]["content"]

    def test_parse_failure_raises_with_raw(self, cfg):
        ai_ready(cfg)
        client, s = self._session(cfg, ["I will just run ls for you"])
        with pytest.raises(cm.CommandError) as ei:
            s.start("list files")
        assert "I will just run ls for you" in str(ei.value)
        assert s.executed == []
        assert s.finished

    def test_unknown_tool_fails_loudly(self, cfg):
        ai_ready(cfg)
        raw = json.dumps({"tool_calls": [
            {"name": "open_app", "arguments": {"command": "firefox"}}]})
        client, s = self._session(cfg, [raw])
        with pytest.raises(cm.CommandError) as ei:
            s.start("open firefox")
        assert "open_app" in str(ei.value)
        assert s.executed == [] and s.finished

    def test_transport_error_wrapped(self, cfg):
        ai_ready(cfg)

        class Broken:
            def chat_messages(self, messages, temperature=None):
                raise AIError("HTTP 500")

        s = cm.CommandSession(cfg, client=Broken())
        with pytest.raises(cm.CommandError, match="HTTP 500"):
            s.start("x")

    def test_messages_shape(self, cfg):
        ai_ready(cfg)
        client, s = self._session(
            cfg,
            [reply(("echo hi", "p")), done_reply("ok")])
        s.start("say hi")
        s.confirm()
        msgs = client.calls[-1]
        assert msgs[0]["role"] == "system"
        assert "terminal agent" in msgs[0]["content"]
        assert "JSON" in msgs[0]["content"]
        assert "tool_calls" in msgs[0]["content"]
        assert [m["role"] for m in msgs] == \
            ["system", "user", "assistant", "user"]
        assert msgs[1]["content"] == "say hi"
        assert msgs[2]["content"].startswith('{"tool_calls"')
        assert msgs[3]["content"].startswith("Command results (JSON):")

    def test_history_saved_via_history_module_when_default(self, cfg,
                                                           tmp_path, monkeypatch):
        """Default appender path: honors history.save via history_mod.append."""
        ai_ready(cfg)
        written = []
        monkeypatch.setattr(cm.history_mod, "append", written.append)
        client, s = self._session(
            cfg, [reply(("echo yes",)), done_reply("ok")])
        s.start("x")
        s.confirm()
        assert len(written) == 1 and written[0]["mode"] == "command"

    def test_history_save_false_noops(self, cfg):
        ai_ready(cfg)
        cfg["history"]["save"] = False
        client, s = self._session(
            cfg, [reply(("echo no",)), done_reply("ok")])
        s.start("x")
        s.confirm()
        assert s.executed  # command ran, history just not persisted


class TestRunShell:
    def test_success(self, tmp_path):
        out = cm.run_shell("echo hello", cwd=tmp_path, timeout=10)
        assert out.success and out.exit_code == 0
        assert "hello" in out.output

    def test_stderr_in_output(self):
        out = cm.run_shell("echo err 1>&2", timeout=10)
        assert "err" in out.output

    def test_nonzero_exit(self):
        out = cm.run_shell("exit 3", timeout=10)
        assert out.exit_code == 3 and out.success is False

    def test_timeout_is_outcome_not_exception(self):
        out = cm.run_shell("sleep 5", cwd=None, timeout=0.3)
        assert out.success is False
        assert out.exit_code == -1
        assert "timed out" in out.error

    def test_output_clipping(self):
        long_text = "x" * 5000
        clipped = cm._clip_output(long_text)
        assert len(clipped) < len(long_text)
        assert "…" in clipped
        assert cm._clip_output("short") == "short"


class TestWorkingDir:
    def test_default_is_home(self, cfg):
        assert cm.working_dir(cfg) == __import__("pathlib").Path.home()

    def test_configured_dir(self, cfg, tmp_path):
        cfg["command"]["working_dir"] = str(tmp_path)
        assert cm.working_dir(cfg) == tmp_path

    def test_nonexistent_falls_back_to_home(self, cfg, tmp_path):
        cfg["command"]["working_dir"] = str(tmp_path / "nope")
        assert cm.working_dir(cfg) == __import__("pathlib").Path.home()


# ---------------------------------------------------------------------------
# Pipeline routing (Phase 4 tests continue below)
# ---------------------------------------------------------------------------

from fluidvoice import daemon as dm  # noqa: E402


class TestPipelineCommandMode:
    def test_command_mode_returns_instruction_without_side_effects(
            self, tmp_path, cfg, quiet_ui):
        inserted, history = [], []
        pipe = dm.DictationPipeline(
            cfg, StubBackend("um list my files"),
            inserter=lambda t, c: inserted.append(t) or "typed",
            history_writer=lambda entry, wav: history.append(entry))
        wav = make_wav(tmp_path / "utt.wav")
        out = pipe.run(wav, None, mode="command")
        assert out["mode"] == "command"
        assert out["text"] and out["raw"]
        assert inserted == [] and history == []
        assert not (tmp_path / "utt.wav").exists()


class TestDaemonCommandMode:
    """Daemon wiring: recording start, mode routing, flag hygiene, the
    pending/confirm/cancel lifecycle, timeout and hotkey lifecycle."""

    def _daemon(self, cfg, recorder=None, pipeline_factory=None):
        d = dm.Daemon(cfg, recorder=recorder or StubRecorder(),
                      backend_factory=lambda c: StubBackend("x"),
                      pipeline_factory=pipeline_factory or dm.DictationPipeline,
                      use_hotkey=False, use_sounds=False)
        d.backend = StubBackend("x")
        return d

    def _wait(self, cond, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.02)
        return False

    # -- recording start -------------------------------------------------------

    def test_start_command_refuses_without_ai(self, cfg, quiet_ui):
        d = self._daemon(cfg)
        d.start_command()
        assert d.recording is False
        assert any("Command mode unavailable" in (t + b)
                   for t, b in quiet_ui["notify"])

    def test_start_command_records(self, cfg, quiet_ui):
        ai_ready(cfg)
        rec = StubRecorder()
        d = self._daemon(cfg, recorder=rec)
        d.start_command()
        assert d.recording is True
        assert d._command_mode is True
        assert rec.started == 1
        d.cancel()

    # -- mode routing ------------------------------------------------------------

    def test_mode_routing(self, cfg, quiet_ui):
        ai_ready(cfg)
        seen = {}

        class CapturingPipeline:
            def __init__(self, c, backend):
                pass

            def run(self, wav, app_hint, mode="dictate",
                    rewrite_context=None):
                seen["mode"] = mode
                return {"mode": "command", "text": "list files",
                        "raw": "list files"}

        # done-immediately session: turn 1 finishes without a proposal
        d = self._daemon(cfg, pipeline_factory=CapturingPipeline)
        d._command_session_factory = lambda c: cm.CommandSession(
            c, client=StubAIClient(['{"done": true, "summary": "nothing"}']))
        d.start_command()
        d.toggle()
        assert self._wait(lambda: seen.get("mode") == "command"
                          and not d.busy
                          and not d._command_pending)
        assert d.last_result["mode"] == "command"
        assert d._command_mode is False

    def test_no_audio_resets_flags(self, cfg, quiet_ui):
        ai_ready(cfg)
        seen = {}

        class CapturingPipeline:
            def __init__(self, c, backend):
                pass

            def run(self, wav, app_hint, mode="dictate",
                    rewrite_context=None):
                seen.setdefault("modes", []).append(mode)
                return {"text": "ok", "raw": "ok"}

        class NoAudioRecorder(StubRecorder):
            def stop(self):
                self.stopped += 1
                if self.stopped == 1:
                    return None
                return self.path

        d = self._daemon(cfg, recorder=NoAudioRecorder(),
                         pipeline_factory=CapturingPipeline)
        d.start_command()
        d._rewrite_mode = True  # the pre-existing bug: flag survived no-audio
        d.toggle()              # no audio -> early return path
        assert d._command_mode is False
        assert d._rewrite_mode is False
        d.toggle()              # follow-up plain dictation
        d.toggle()
        assert self._wait(lambda: seen.get("modes") == ["dictate"]
                          and not d.busy)

    def test_escape_during_recording_resets_flags(self, cfg, quiet_ui):
        ai_ready(cfg)
        seen = {}

        class CapturingPipeline:
            def __init__(self, c, backend):
                pass

            def run(self, wav, app_hint, mode="dictate",
                    rewrite_context=None):
                seen.setdefault("modes", []).append(mode)
                return {"text": "ok", "raw": "ok"}

        d = self._daemon(cfg, pipeline_factory=CapturingPipeline)
        d.start_command()
        assert d.recording
        d.cancel()
        assert d.recording is False
        assert d._command_mode is False
        assert d._rewrite_mode is False
        d.toggle()
        d.toggle()
        assert self._wait(lambda: seen.get("modes") == ["dictate"])

    # -- pending proposal / confirm / cancel lifecycle --------------------------

    def _pending(self, cfg, monkeypatch, replies=None, runner=None):
        """Daemon with a proposal pending: patched pill + fake hotkey grab."""
        ai_ready(cfg)
        pills = []

        class CapturingPanel:
            using_overlay = True

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.updates = []          # (entries, status, awaiting)
                self.started = 0
                self.closed = 0
                pills.append(self)

            def update(self, entries, status=None, awaiting=None):
                self.updates.append((list(entries), status, awaiting))

            def start(self):
                self.started += 1

            def close(self):
                self.closed += 1

        monkeypatch.setattr("fluidvoice.overlay.CommandPanel", CapturingPanel)
        hk = FakeCommandHotkey()
        client = StubAIClient(replies or [reply(("echo hello", "greet"))])
        sessions = []

        def factory(c):
            kw = {"client": client}
            if runner is not None:
                kw["runner"] = runner
            s = cm.CommandSession(c, **kw)
            sessions.append(s)
            return s

        d = self._daemon(cfg)
        d._command_session_factory = factory
        d._command_hotkey = hk
        d._begin_command("list files")
        assert self._wait(lambda: d._command_pending), "proposal never landed"
        assert pills, "pill never built"
        return d, pills[-1], hk, client, sessions

    def test_propose_shows_confirmation_panel(self, cfg, quiet_ui, monkeypatch):
        d, pill, hk, client, sessions = self._pending(cfg, monkeypatch)
        assert pill.updates, "panel never updated"
        entries, status, awaiting = pill.updates[-1]
        texts = " ".join(str(e.get("text", "")) + str(e.get("sub", ""))
                         for e in entries)
        assert "echo hello" in texts and "greet" in texts
        assert "list files" in texts           # instruction is in the feed
        assert awaiting and "Esc" in awaiting  # confirm hint armed
        assert pill.started == 1
        assert hk.armed == [True]      # Escape grab armed
        assert "bottom_offset" in pill.kwargs  # panel built with daemon geometry
        assert any("Esc" in (t + b) for t, b in quiet_ui["notify"])
        assert d.busy is False         # waiting for the user, not busy
        assert d._command_timer is not None
        d.cancel_pending_command()

    def test_confirm_executes_and_logs_history(self, cfg, quiet_ui,
                                               monkeypatch, tmp_path):
        d, pill, hk, client, sessions = self._pending(
            cfg, monkeypatch,
            replies=[reply(("echo hello", "greet")), done_reply("all done")])
        d._on_command_hotkey()   # the confirm press
        assert self._wait(lambda: not d.busy and d._command_session is None)
        hist = tmp_path / "test-history.jsonl"
        assert hist.exists()
        import json as _json
        entries = [_json.loads(ln) for ln in
                   hist.read_text().splitlines() if ln.strip()]
        cmds = [e for e in entries if e.get("mode") == "command"]
        assert len(cmds) == 1
        assert cmds[0]["command"] == "echo hello"
        assert "hello" in cmds[0]["output"]
        assert cmds[0]["text"] == "$ echo hello"
        notes = " ".join(t + b for t, b in quiet_ui["notify"])
        assert "exit 0" in notes
        assert "all done" in notes
        summary = [u for u in pill.updates
                   if any(e.get("kind") == "summary" for e in u[0])]
        assert summary and "all done" in summary[-1][0][-1]["text"]
        for u in pill.updates:     # no stale confirm hint afterwards
            pass
        assert summary[-1][2] is None
        assert hk.armed[-1] is False and True in hk.armed  # disarmed after run

    def test_escape_cancel_executes_nothing(self, cfg, quiet_ui, monkeypatch,
                                            tmp_path):
        runs = []

        def runner(cmd, cwd=None, timeout=None):
            runs.append(cmd)
            return cm.CommandOutcome(command=cmd, success=True, exit_code=0,
                                     output="should never happen")

        d, pill, hk, client, sessions = self._pending(cfg, monkeypatch,
                                                      runner=runner)
        d.cancel_pending_command()
        assert sessions[0].cancelled and sessions[0].finished
        assert runs == []
        hist = tmp_path / "test-history.jsonl"
        entries = []
        if hist.exists():
            import json as _json
            entries = [_json.loads(ln) for ln in
                       hist.read_text().splitlines() if ln.strip()]
        assert [e for e in entries if e.get("mode") == "command"] == []
        assert any("Command cancelled" in (t + b)
                   for t, b in quiet_ui["notify"])
        assert pill.closed >= 1
        assert hk.armed[-1] is False and True in hk.armed  # disarmed
        # a stray hotkey press afterwards is harmless: nothing executes,
        # no session is created, no notification fires (it may open a fresh
        # command recording, exactly like the rewrite hotkey after a cancel)
        before = list(quiet_ui["notify"])
        d._on_command_hotkey()
        assert d._command_pending is False and not d.busy
        assert runs == []
        assert quiet_ui["notify"] == before
        d.cancel()
        assert d.recording is False

    def test_confirm_timeout_cancels(self, cfg, quiet_ui, monkeypatch):
        d, pill, hk, client, sessions = self._pending(cfg, monkeypatch)
        d._on_confirm_timeout()   # deterministic: the timer's callback
        assert d._command_pending is False
        assert sessions[0].cancelled
        assert any("confirmation timed out" in (t + b)
                   for t, b in quiet_ui["notify"])

    def test_on_command_hotkey_routes(self, cfg, quiet_ui, monkeypatch):
        ai_ready(cfg)
        d = self._daemon(cfg)
        confirm_calls = []
        monkeypatch.setattr(d, "_confirm_pending_command",
                            lambda: confirm_calls.append(1))
        d._command_pending = True
        d._on_command_hotkey()
        assert confirm_calls == [1]
        # not pending -> start_command (guarded: busy makes it a no-op)
        d._command_pending = False
        d.busy = True
        d._on_command_hotkey()
        assert d.recording is False
        assert confirm_calls == [1]

    def test_restart_and_shutdown_cover_command_hotkey(self, cfg, quiet_ui,
                                                       monkeypatch):
        d = self._daemon(cfg)
        d.use_hotkey = True
        stopped = []

        class FakeListener:
            def stop(self):
                stopped.append(1)

        d._command_hotkey = FakeListener()
        started = []
        monkeypatch.setattr(d, "_start_hotkey", lambda: started.append(1))
        out = d.apply_config(["hotkey.command_key"])
        assert stopped == [1] and started == [1]
        assert out == {"applied": ["hotkeys"], "errors": []}
        d._command_hotkey = FakeListener()
        d.shutdown()
        assert stopped == [1, 1]


class FakeCommandHotkey:
    def __init__(self):
        self.armed = []

    def set_recording(self, active):
        self.armed.append(active)

    def stop(self):
        pass
