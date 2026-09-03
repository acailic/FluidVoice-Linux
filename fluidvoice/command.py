"""Command mode - voice-driven terminal agent (Linux port of upstream
CommandModeService, deliberately diverging: strict-JSON single-tool protocol
instead of native tool_calls, every command confirm-gated).

The user dictates an instruction; the LLM proposes ONE shell command at a
time via a strict JSON reply; the daemon shows it in the pill overlay in an
awaiting-confirmation state; the command hotkey confirms and executes,
Escape cancels. Output is fed back as a user message and the loop continues,
bounded by command.max_turns. Nothing ever runs without the confirm press -
CommandSession.confirm() is the only execution site in the codebase.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import history as history_mod
from .ai.client import AIClient, AIError, strip_thinking


def log(msg: str) -> None:
    import sys
    print(f"[fluidvoice] {time.strftime('%H:%M:%S')} {msg}",
          file=sys.stderr, flush=True)


SYSTEM_PROMPT = """\
You are a careful Linux terminal agent. The user speaks an instruction; you
accomplish it by proposing ONE shell command at a time. Every proposal is
shown to the user and only runs after they confirm it.

Respond with EXACTLY ONE JSON object and nothing else - no markdown fences,
no prose before or after:

  {"command": "<one shell command>", "purpose": "<short reason>", "done": false}

When the task is complete (or nothing needs to run), respond with:

  {"command": "", "purpose": "", "done": true, "summary": "<what happened, 1-3 sentences>"}

Rules:
- One command per reply. Chain with && or ; only when it is genuinely one step.
- Check before acting: list or test -e before deleting or overwriting; read
  before editing; check --version before installing.
- Verify after acting, then finish with done=true and a short summary.
- Non-interactive commands only: never propose password prompts, editors,
  top, or anything that waits for input.
- Quote paths with spaces; prefer absolute paths.
- Commands run in the user's shell in the working directory; after each one
  you receive its stdout+stderr, exit code and duration as JSON.
"""


class CommandError(RuntimeError):
    """Carries user-readable text (shown verbatim in notifications)."""


@dataclass
class PendingCommand:
    command: str
    purpose: str | None = None


@dataclass
class CommandOutcome:
    """Execution result (never raised)."""
    command: str
    success: bool
    exit_code: int
    output: str  # stdout+stderr combined
    error: str | None = None
    duration_ms: int = 0


@dataclass
class ParsedReply:
    kind: str  # "proposal" | "done"
    proposal: PendingCommand | None = None
    summary: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers (unit-test targets)
# ---------------------------------------------------------------------------

def command_mode_ready(cfg: dict) -> str | None:
    """None when command mode may run, else the readiness issue (rewrite's
    wording, adapted) - checked before recording and again in the session."""
    if not cfg["ai"].get("enabled"):
        return "command mode needs [ai] enabled with a model"
    if not (cfg["ai"].get("base_url") and cfg["ai"].get("model")):
        return "AI enabled but base_url/model not configured"
    return None


_FENCE_RE = re.compile(
    r"^```[ \t]*[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)\r?\n?```\s*$", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Strip a leading ```json / ``` line and a trailing ``` line (tolerates
    language tags and stray spaces). Bare text passes through unchanged."""
    if not text:
        return text
    out = text.strip()
    m = _FENCE_RE.match(out)
    if m:
        return m.group(1).strip()
    return out


def parse_reply(content: str) -> ParsedReply:
    """Model output is never trusted: <think> stripped, fences stripped,
    JSON parsed (one tolerant brace-slice retry). Raises CommandError with
    the raw text embedded when nothing parses."""
    cleaned = strip_code_fences(strip_thinking(content))
    data = None
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        first, last = cleaned.find("{"), cleaned.rfind("}")
        if first >= 0 and last > first:
            try:
                data = json.loads(cleaned[first:last + 1])
            except (json.JSONDecodeError, ValueError):
                data = None
    if not isinstance(data, dict):
        raise CommandError(
            f"could not parse the model's proposal: {cleaned}")
    if data.get("done"):
        summary = data.get("summary")
        return ParsedReply("done", summary=str(summary) if summary else "Done.")
    command = data.get("command")
    if isinstance(command, str) and command.strip():
        purpose = data.get("purpose")
        return ParsedReply("proposal",
                           PendingCommand(command.strip(),
                                          str(purpose) if purpose else None))
    raise CommandError(f"could not parse the model's proposal: {cleaned}")


def working_dir(cfg: dict) -> Path:
    """Expand the configured working directory ("" -> ~); fall back to home
    (with a warning) when it is not a directory - never crash."""
    raw = str(cfg.get("command", {}).get("working_dir") or "~").strip() or "~"
    p = Path(raw).expanduser()
    if not p.is_dir():
        log(f"WARN command working_dir is not a directory, using home: {p}")
        return Path.home()
    return p


def run_shell(command: str, cwd: Path | None = None,
              timeout: float = 60.0) -> CommandOutcome:
    """`bash -c` (falls back to `sh -c`) with a timeout. TimeoutExpired /
    OSError become failure outcomes, never exceptions."""
    shell = "/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"
    started = time.monotonic()

    def _ms() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        proc = subprocess.run([shell, "-c", command],
                              cwd=str(cwd) if cwd else None,
                              capture_output=True, text=True, timeout=timeout)
        output = (proc.stdout or "") + (proc.stderr or "")
        return CommandOutcome(command=command,
                              success=proc.returncode == 0,
                              exit_code=proc.returncode, output=output,
                              duration_ms=_ms())
    except subprocess.TimeoutExpired as e:
        partial = ""
        for chunk in (e.stdout, e.stderr):
            if chunk:
                partial += chunk.decode(errors="replace") \
                    if isinstance(chunk, bytes) else str(chunk)
        return CommandOutcome(command=command, success=False, exit_code=-1,
                              output=partial,
                              error=f"timed out after {timeout}s",
                              duration_ms=_ms())
    except OSError as e:
        return CommandOutcome(command=command, success=False, exit_code=-1,
                              output="", error=str(e), duration_ms=_ms())


def _clip_output(text: str, head: int = 3000, tail: int = 1000) -> str:
    """Result feedback to the model: first 3000 + ellipsis + last 1000."""
    if len(text) <= head + tail + 1:
        return text
    return text[:head] + "\n…\n" + text[-tail:]


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------

class CommandSession:
    """One command-mode run: instruction -> proposals -> confirmations -> done.
    Fully injectable (client / runner / history appender) for tests. A shell
    command executes ONLY from confirm() - no auto-execution anywhere."""

    def __init__(self, cfg: dict, *, client=None, runner=None,
                 history_appender=None, log_fn=None):
        self.cfg = cfg
        self.client = client
        self.runner = runner or run_shell
        self.history_appender = history_appender
        self.log = log_fn or log
        self.messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}]
        self.instruction: str | None = None
        self.pending: PendingCommand | None = None
        self.finished = False  # done / exhausted / cancelled / errored
        self.exhausted = False  # hit max_turns
        self.cancelled = False
        self.summary: str | None = None
        self.executed: list[CommandOutcome] = []
        self.turns = 0  # LLM calls made

    # -- public API -----------------------------------------------------------

    def start(self, instruction: str) -> PendingCommand | None:
        ready = command_mode_ready(self.cfg)
        if ready:
            raise CommandError(ready)
        self.client = self.client or AIClient(self.cfg)
        self.instruction = instruction
        self.messages.append({"role": "user", "content": instruction})
        return self._advance()

    def confirm(self) -> PendingCommand | None:
        """Execute the pending proposal (the ONLY execution site) and feed
        the result back for the next turn."""
        if self.finished:
            raise CommandError("session is over")
        if self.pending is None:
            raise CommandError("no pending command")
        proposal = self.pending
        outcome = self.runner(proposal.command,
                              cwd=working_dir(self.cfg),
                              timeout=float(self.cfg["command"].get(
                                  "timeout_seconds", 60.0)))
        if not isinstance(outcome, CommandOutcome):
            outcome = CommandOutcome(command=proposal.command,
                                     success=False, exit_code=-1,
                                     output=str(outcome))
        self.executed.append(outcome)
        self.pending = None
        self._write_history(proposal, outcome)
        result = {"command": outcome.command,
                  "exit_code": outcome.exit_code,
                  "success": outcome.success,
                  "output": _clip_output(outcome.output),
                  "error": outcome.error,
                  "duration_ms": outcome.duration_ms}
        self.messages.append({"role": "user",
                              "content": "Command result (JSON): "
                                         + json.dumps(result)})
        return self._advance()

    def cancel(self) -> None:
        """Nothing executes; no history."""
        self.pending = None
        self.cancelled = True
        self.finished = True

    # -- internals --------------------------------------------------------------

    def _advance(self) -> PendingCommand | None:
        if self.turns >= int(self.cfg["command"].get("max_turns", 4)):
            self.exhausted = True
            self.finished = True
            self.summary = ("Reached maximum steps limit. Please review the "
                            "progress and continue if needed.")
            return None
        self.turns += 1
        try:
            content = self.client.chat_messages(self.messages,
                                                temperature=0.1)
        except AIError as e:
            raise CommandError(str(e)) from e
        self.messages.append({"role": "assistant", "content": content})
        try:
            reply = parse_reply(content)
        except CommandError:
            self.finished = True  # errored: raw text is in the exception
            raise
        if reply.kind == "done":
            self.summary = reply.summary
            self.finished = True
            return None
        self.pending = reply.proposal
        return self.pending

    def _write_history(self, proposal: PendingCommand,
                       outcome: CommandOutcome) -> None:
        """ONE history entry per executed command, no matter the exit code.
        Cancellations and parse failures never get here (nothing executed)."""
        entry = {"ts": time.time(), "mode": "command",
                 "raw": self.instruction or "",
                 "text": f"$ {proposal.command}",
                 "command": proposal.command,
                 "purpose": proposal.purpose,
                 "exit_code": outcome.exit_code,
                 "success": outcome.success,
                 "output": outcome.output[:2000],
                 "duration_ms": outcome.duration_ms,
                 "backend": "shell"}
        if self.history_appender is not None:
            self.history_appender(entry)
            return
        if not self.cfg["history"].get("save"):
            return
        history_mod.append(entry)
