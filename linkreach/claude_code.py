"""Reach Claude through the locally installed Claude Code CLI (`claude -p`), signed in with
the user's own account, for people without an Anthropic API key (ticket 12).

`ClaudeCodeClient` offers the one call linkreach makes on the Anthropic SDK client,
`client.beta.messages.create(...)`, so `llm.structured_call` and everything above it is
unchanged.

The CLI runs as a plain text-in, JSON-out model call, never as an agent (ADR-0002): the
prompt carries untrusted scraped text, so the model must not be able to act on anything.
- `--tools ""`: no built-in tools at all.
- `--strict-mcp-config` with no `--mcp-config`: no MCP servers.
- `--setting-sources ""`: no user, project, or local settings (so no hooks or permissions
  from them), and `--disable-slash-commands`: no skills or custom commands.
- The working directory is a fresh, empty temp folder, so no CLAUDE.md or project files load.
- `--no-session-persistence`: nothing is saved to disk as a resumable session.
The system prompt goes in a file (`--system-prompt-file`, outside the working folder) and
the user message on stdin, never on the command line: the Job flow's system prompt can pass
Windows' 32K command-line limit, and both carry scraped text that shouldn't show up in
process listings.

Nothing here logs prompts or outputs; `llm.structured_call` logs token counts only.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 - fixed argv to the user's own `claude` executable, no shell
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from linkreach import sanitize

PING_TIMEOUT = 60.0


class ClaudeCodeError(ValueError):
    """A Claude Code call failed. The message is safe to show the user: it never holds the
    prompt or the model's output. A ValueError, so the drafters record it like any other
    bad reply instead of crashing."""


class ClaudeCodeNotFound(RuntimeError):
    """`claude` isn't installed where config.yaml says. A RuntimeError, like a missing API
    key, so commands stop before doing any work."""


@dataclass
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes


# argv, stdin bytes, working directory, timeout seconds -> result. Raises
# subprocess.TimeoutExpired on a timeout. Tests inject a fake; real `claude` never runs in tests.
Runner = Callable[[list[str], bytes, str, float], RunResult]


def subprocess_runner(argv: list[str], stdin: bytes, cwd: str, timeout: float) -> RunResult:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    p = subprocess.run(  # nosec B603 - list argv, shell=False
        argv, input=stdin, capture_output=True, cwd=cwd, timeout=timeout, check=False, creationflags=flags
    )
    return RunResult(p.returncode, p.stdout, p.stderr)


def resolve_executable(configured: str, which: Callable[[str], str | None] | None = None) -> str | None:
    """Full path to `claude`: a bare name is looked up on PATH; a path is used if it exists."""
    which = which or shutil.which
    raw = os.path.expandvars(os.path.expanduser(configured.strip()))
    if not raw:
        return None
    if os.path.dirname(raw):
        p = Path(raw)
        if p.is_file():
            return str(p)
        return which(raw)  # e.g. a path given without .exe on Windows
    return which(raw)


def not_found_message(configured: str) -> str:
    return (
        f"Claude Code (`{configured}`) not found: install Claude Code, or set claude_code_path "
        "in config.yaml to the full path of the claude executable"
    )


SIGN_IN_RE = re.compile(r"not logged in|/login|please log ?in|sign in|invalid api key|oauth|authenticat|unauthori[sz]ed|401", re.I)
USAGE_LIMIT_RE = re.compile(r"usage limit|hit your limit|limit reached|rate limit|out of (extra )?usage|quota|429", re.I)

SIGN_IN_MSG = "Claude Code isn't signed in: run `claude` once in a terminal and sign in (/login)"
USAGE_LIMIT_MSG = "Claude Code hit your plan's usage limit"


def _detail(text: str) -> str:
    return sanitize.clean_line(text or "", 200)


def _classify(text: str, fallback: str) -> ClaudeCodeError:
    if SIGN_IN_RE.search(text or ""):
        return ClaudeCodeError(SIGN_IN_MSG)
    if USAGE_LIMIT_RE.search(text or ""):
        detail = _detail(text)
        return ClaudeCodeError(f"{USAGE_LIMIT_MSG}: {detail}" if detail else USAGE_LIMIT_MSG)
    return ClaudeCodeError(fallback)


def _usage(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return None
    return SimpleNamespace(
        input_tokens=raw.get("input_tokens"),
        cache_read_input_tokens=raw.get("cache_read_input_tokens"),
        cache_creation_input_tokens=raw.get("cache_creation_input_tokens"),
        output_tokens=raw.get("output_tokens"),
    )


def parse_result(proc: RunResult) -> Any:
    """Map the CLI's `--output-format json` result onto the SDK response shape
    `llm.structured_call` reads: `.content` (a text block holding the JSON), `.stop_reason`,
    and `.usage`. Result fields confirmed against Claude Code 2.1.322 (see ticket 12)."""
    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(stdout) if stdout else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        if proc.returncode != 0:
            raise _classify(stderr or stdout, f"Claude Code exited with code {proc.returncode}: {_detail(stderr) or 'no output'}")
        raise ClaudeCodeError("Claude Code returned output linkreach couldn't read (expected one JSON result)")

    if data.get("stop_reason") == "refusal" or data.get("terminal_reason") == "refusal":
        return SimpleNamespace(content=[], stop_reason="refusal", usage=_usage(data.get("usage")))

    message = str(data.get("result") or "")
    if data.get("is_error") or proc.returncode != 0 or data.get("subtype", "success") != "success":
        # With is_error set, `result` is the CLI's error text, not model output.
        status = data.get("api_error_status")
        subtype = data.get("subtype")
        fallback = f"Claude Code call failed ({subtype if subtype and subtype != 'success' else 'error'}"
        fallback += f", HTTP {status})" if status else ")"
        if message:
            fallback += f": {_detail(message)}"
        raise _classify(f"{message} {stderr} {status or ''}", fallback)

    structured = data.get("structured_output")
    if structured is not None:
        text = json.dumps(structured)
    elif message:
        text = message  # llm.structured_call parses it, and rejects it if it isn't JSON
    else:
        raise ClaudeCodeError("Claude Code returned no answer")
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=_usage(data.get("usage")),
    )


def build_argv(executable: str, model: str, schema: dict[str, Any], system_file: str) -> list[str]:
    return [
        executable,
        "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(schema, separators=(",", ":")),
        "--system-prompt-file", system_file,
        "--model", model,
        "--no-session-persistence",
        # Lockdown: text in, JSON out. No tools, no MCP servers, no settings, no skills.
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--disable-slash-commands",
    ]


def system_text(system: Any) -> str:
    """The SDK's system blocks joined into one prompt. `cache_control` is an API-only
    feature and is dropped."""
    if isinstance(system, str):
        return system
    return "\n\n".join(str(b.get("text", "")) for b in system or [] if isinstance(b, dict))


def user_text(messages: list[dict[str, Any]]) -> str:
    if len(messages) != 1 or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), str):
        raise ClaudeCodeError("the Claude Code backend takes exactly one plain-text user message")
    return messages[0]["content"]


class _Messages:
    def __init__(self, owner: "ClaudeCodeClient"):
        self._owner = owner

    def create(self, **kw: Any) -> Any:
        return self._owner.create(**kw)


class ClaudeCodeClient:
    """Drop-in for the Anthropic client's `beta.messages.create` structured-output call."""

    def __init__(self, executable: str, timeout: float = 120.0, runner: Runner | None = None):
        self.executable = executable
        self.timeout = timeout
        self.runner: Runner = runner or subprocess_runner
        self.beta = SimpleNamespace(messages=_Messages(self))
        self.messages = self.beta.messages

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: Any = None,
        output_config: dict[str, Any] | None = None,
        timeout: float | None = None,
        **_api_only: Any,  # max_tokens, betas, fallbacks: API-only, ignored here
    ) -> Any:
        try:
            schema = (output_config or {})["format"]["schema"]
        except (KeyError, TypeError):
            raise ClaudeCodeError("the Claude Code backend needs a JSON schema for every call") from None
        user = user_text(messages)
        limit = timeout or self.timeout
        with tempfile.TemporaryDirectory(prefix="linkreach-claude-") as tmp:
            work = Path(tmp) / "work"
            work.mkdir()  # empty working folder: no CLAUDE.md, no project files
            system_file = Path(tmp) / "system-prompt.txt"
            system_file.write_text(system_text(system), encoding="utf-8")
            argv = build_argv(self.executable, model, schema, str(system_file))
            try:
                proc = self.runner(argv, user.encode("utf-8"), str(work), limit)
            except subprocess.TimeoutExpired:
                raise ClaudeCodeError(f"Claude Code didn't answer within {limit:g} seconds") from None
            except FileNotFoundError:
                raise ClaudeCodeError(not_found_message(self.executable)) from None
            except OSError as exc:
                raise ClaudeCodeError(f"couldn't start Claude Code: {exc.strerror or type(exc).__name__}") from None
        return parse_result(proc)

    def ping(self, model: str, timeout: float = PING_TIMEOUT) -> None:
        """A tiny no-tools call that proves the CLI runs and is signed in. Raises
        ClaudeCodeError otherwise."""
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
        resp = self.create(
            model=model,
            system="You answer health checks. Reply with ok set to true.",
            messages=[{"role": "user", "content": "health check"}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            timeout=timeout,
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            raise ClaudeCodeError("Claude Code declined the health check")
