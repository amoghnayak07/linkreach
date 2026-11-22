"""The one way linkreach calls Claude: a structured-output request on an injectable client.

Every Claude call (drafting, Job extraction) goes through `structured_call` with a client
from `make_client`, so swapping how Claude is reached (ticket 12) touches one place.
Prompts and outputs are never logged; only token counts are.
"""

from __future__ import annotations

import json
from typing import Any

from linkreach import credentials, logsetup
from linkreach.config import Config

log = logsetup.get("llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Refused(ValueError):
    """The model declined the request."""


def make_client() -> Any:
    import anthropic

    key = credentials.api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not found (run `linkreach set-key` or add it to .env)")
    # The SDK retries 408/409/429/5xx and connection errors with exponential backoff.
    return anthropic.Anthropic(api_key=key, max_retries=6, timeout=120.0)


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
    if cfg.use_refusal_fallbacks:
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
