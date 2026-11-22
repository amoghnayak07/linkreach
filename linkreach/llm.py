"""The one way linkreach calls Claude: a structured-output request on an injectable client.

Every Claude call (drafting, Job extraction) goes through `structured_call` with a client
from `make_client`. `cfg.llm_backend` picks how Claude is reached: `api` (the Anthropic SDK
with an API key) or `claude_code` (the local Claude Code CLI, signed in with the user's own
account; see claude_code.py). Callers never know which one they have.
Prompts and outputs are never logged; only token counts are.
"""

from __future__ import annotations

import json
from typing import Any

from linkreach import credentials, logsetup
from linkreach.config import Config

log = logsetup.get("llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Parallel drafting calls. Each Claude Code call starts a process, so it gets fewer.
MAX_PARALLEL_API = 5
MAX_PARALLEL_CLAUDE_CODE = 2


class Refused(ValueError):
    """The model declined the request."""


def make_client(cfg: Config) -> Any:
    """The configured client. Raises RuntimeError (shown to the user as-is) when it can't
    be built: no API key for `api`, no `claude` executable for `claude_code`."""
    if cfg.llm_backend == "claude_code":
        from linkreach import claude_code

        exe = claude_code.resolve_executable(cfg.claude_code_path)
        if exe is None:
            raise claude_code.ClaudeCodeNotFound(claude_code.not_found_message(cfg.claude_code_path))
        return claude_code.ClaudeCodeClient(exe, timeout=float(cfg.claude_code_timeout_seconds))

    import anthropic

    key = credentials.api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found (run `linkreach set-key` or add it to .env)")
    # The SDK retries 408/409/429/5xx and connection errors with exponential backoff.
    return anthropic.Anthropic(api_key=key, max_retries=6, timeout=120.0)


def max_parallel(cfg: Config) -> int:
    return MAX_PARALLEL_CLAUDE_CODE if cfg.llm_backend == "claude_code" else MAX_PARALLEL_API


def structured_call(
    client: Any,
    cfg: Config,
    system: list[dict[str, Any]],
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 8000,
) -> dict[str, Any]:
    """One request whose reply must be a JSON object matching `schema`.
    Raises Refused, ValueError, or json.JSONDecodeError on a bad reply."""
    kwargs: dict[str, Any] = dict(
        model=cfg.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    # Server-side fallbacks are API-only; with claude_code they're skipped silently.
    if cfg.use_refusal_fallbacks and cfg.llm_backend == "api":
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"
    resp = client.beta.messages.create(**kwargs)
    if getattr(resp, "stop_reason", None) == "refusal":
        raise Refused("model declined to write this draft")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    usage = getattr(resp, "usage", None)
    if usage is not None:
        logsetup.event(
            log,
            "api call",
            backend=cfg.llm_backend,
            model=cfg.model,
            input_tokens=getattr(usage, "input_tokens", None),
            cache_read=getattr(usage, "cache_read_input_tokens", None),
            cache_write=getattr(usage, "cache_creation_input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("model returned non-object JSON")
    return data
