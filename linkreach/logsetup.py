"""Structured JSON logs with rotation (10 MB x 5) and redaction.

Redaction runs on every record before it is written: API keys, cookies, and any
field that could hold a message body are scrubbed. Code never passes note or
follow-up text to the logger, and the filter is a second line of defense.
"""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from linkreach import clock, credentials, paths

MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5

SENSITIVE_KEYS = {
    "note", "note_draft", "note_sent", "followup", "followup_draft", "message", "body",
    "text", "cookie", "cookies", "set-cookie", "authorization", "api_key", "x-api-key",
    "prompt", "content", "token",
    # Job flow: found emails and everything written for a Pick.
    "email", "found_email", "subject", "email_subject", "email_body", "connection_note",
    "description", "user_detail",
}
_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED_EMAIL]"),
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(li_at|JSESSIONID|li_rm|bcookie|bscookie|lidc)=[^;\s]+"), r"\1=[REDACTED_COOKIE]"),
    (re.compile(r"(?i)(cookie|set-cookie|authorization|x-api-key)\s*[:=]\s*\S+"), r"\1: [REDACTED]"),
]

_extra_secrets: set[str] = set()


def add_secret(value: str | None) -> None:
    """Register an exact string (e.g. the dashboard token) to scrub from logs."""
    if value and len(value) >= 8:
        _extra_secrets.add(value)


def redact(text: str) -> str:
    key = credentials.api_key() if credentials._cached else None
    if key:
        text = text.replace(key, "[REDACTED_API_KEY]")
    for s in _extra_secrets:
        text = text.replace(s, "[REDACTED]")
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": clock.now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            for k, v in fields.items():
                if k.lower() in SENSITIVE_KEYS:
                    payload[k] = "[REDACTED]"
                else:
                    payload[k] = redact(str(v)) if not isinstance(v, (int, float, bool)) or v is None else v
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class _SecureRotatingHandler(RotatingFileHandler):
    def _open(self):  # type: ignore[override]
        stream = super()._open()
        paths.secure_file(Path(self.baseFilename))
        return stream


_configured = False


def setup(verbose: bool = False) -> logging.Logger:
    global _configured
    logger = logging.getLogger("linkreach")
    if _configured:
        return logger
    paths.ensure_home()
    handler = _SecureRotatingHandler(
        paths.logs_dir() / "linkreach.log", maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    # Keep third-party HTTP loggers quiet: they can echo headers.
    for name in ("httpx", "httpx2", "anthropic", "urllib3", "uvicorn.access"):
        logging.getLogger(name).setLevel(logging.WARNING)
    _configured = True
    return logger


def reset() -> None:
    """Testing hook: drop handlers so setup() can point at a new LINKREACH_HOME."""
    global _configured
    logger = logging.getLogger("linkreach")
    for h in list(logger.handlers):
        h.close()
        logger.removeHandler(h)
    _configured = False


def get(name: str = "") -> logging.Logger:
    return logging.getLogger("linkreach" + (f".{name}" if name else ""))


def event(logger: logging.Logger, msg: str, **fields: object) -> None:
    logger.info(msg, extra={"fields": fields})
