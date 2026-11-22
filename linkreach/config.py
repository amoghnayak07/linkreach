"""Load and validate config.yaml with Pydantic.

All problems are collected and reported together, so one run shows every fix you need
to make.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from linkreach import paths

# Absolute ceilings from the build spec. config.yaml may lower these, never raise them.
MAX_DAILY_VIEWS = 40
MAX_DAILY_REQUESTS = 20
MAX_WEEKLY_REQUESTS = 80
MAX_PICK_TARGET = 15

DEFAULT_BANNED_PHRASES = [
    "synergy",
    "leverage",
    "passionate about disrupting",
    "circle back",
    "i hope this finds you well",
]

PROFILE_URL_RE = re.compile(r"^https://(www\.)?linkedin\.com/in/[A-Za-z0-9_\-%.]+/?$")

# Settings of the old company-driven bulk flow (collect / draft / review), now deleted.
# A config that still has one fails with a message naming it, not a generic "extra field".
REMOVED_KEYS = {
    "buckets": "role buckets were for `collect`",
    "per_company_limit": "it capped `collect`",
    "combine_keywords": "it shaped `collect`'s searches",
    "alumni_angle": "the alumni pass is gone; alumni_school still marks alumni",
    "exclude_title_keywords": "it filtered `collect`'s search results",
    "templates": "notes and emails now follow your Style file (style.md)",
    "followup_max_words": "the LinkedIn follow-up message is gone",
}

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ConfigError(Exception):
    """Raised with every validation problem found at startup."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Caps(Strict):
    daily_views: int = Field(MAX_DAILY_VIEWS, ge=1, le=MAX_DAILY_VIEWS)
    daily_requests: int = Field(MAX_DAILY_REQUESTS, ge=1, le=MAX_DAILY_REQUESTS)
    weekly_requests: int = Field(MAX_WEEKLY_REQUESTS, ge=1, le=MAX_WEEKLY_REQUESTS)


class Delay(Strict):
    min_seconds: float = Field(8, ge=8)
    max_seconds: float = Field(25, ge=8)

    @model_validator(mode="after")
    def _order(self) -> "Delay":
        if self.max_seconds < self.min_seconds:
            raise ValueError("delay.max_seconds must be >= delay.min_seconds")
        return self


class Brake(Strict):
    min_sample: int = Field(30, ge=1)
    min_rate: float = Field(0.25, ge=0, le=1)
    age_days: int = Field(7, ge=1)


class AutoWindow(Strict):
    days: list[Weekday] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    start: time = time(9, 0)
    end: time = time(18, 0)

    @model_validator(mode="after")
    def _order(self) -> "AutoWindow":
        if self.end <= self.start:
            raise ValueError("auto_window.end must be after auto_window.start")
        return self


ConnectMode = Literal["manual", "automated"]
LlmBackend = Literal["api", "claude_code"]


class Config(Strict):
    # ADR-0001: automated connection requests are off unless this is "automated".
    connect_mode: ConnectMode = "manual"
    caps: Caps = Caps()
    # `job`: Found picks fill up to this many Picks; Supplied picks are never cut to fit it.
    pick_target: int = Field(5, ge=1, le=MAX_PICK_TARGET)
    delay: Delay = Delay()
    alumni_school: str = "Northeastern"
    background: str = Field(min_length=20)
    resume_url: str
    banned_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_BANNED_PHRASES))
    model: str = "claude-sonnet-5-5"
    # How Claude is reached: "api" (Anthropic API key) or "claude_code" (the local Claude
    # Code CLI, signed in with your own account; no API key).
    llm_backend: LlmBackend = "api"
    claude_code_path: str = Field("claude", min_length=1)
    claude_code_timeout_seconds: int = Field(120, ge=10, le=900)
    use_refusal_fallbacks: bool = True  # API-only; ignored with claude_code
    # Connection note limit: 200 for a free LinkedIn account, 300 with Premium.
    note_max_chars: int = Field(200, ge=50, le=300)
    # The dormant send/sync path (ADR-0001) only: days from acceptance to a follow-up date.
    follow_up_delay_days: int = Field(5, ge=1)
    brake: Brake = Brake()
    auto_window: AutoWindow = AutoWindow()
    chrome_profile_dir: str = "~/.linkreach/chrome-profile"
    chrome_channel: str = "chrome"
    headless: bool = False
    doctor_profile_url: str

    @field_validator("resume_url")
    @classmethod
    def _resume(cls, v: str) -> str:
        if not re.match(r"^https://\S+$", v):
            raise ValueError("resume_url must be an https:// URL")
        return v

    @field_validator("doctor_profile_url")
    @classmethod
    def _doctor(cls, v: str) -> str:
        if not PROFILE_URL_RE.match(v):
            raise ValueError("doctor_profile_url must look like https://www.linkedin.com/in/<slug>/")
        return v

    @field_validator("chrome_profile_dir")
    @classmethod
    def _profile(cls, v: str) -> str:
        from linkreach.browser import ProfileGuardError, guard_profile_dir

        try:
            guard_profile_dir(resolve_profile_dir(v))
        except ProfileGuardError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @property
    def profile_path(self) -> Path:
        return resolve_profile_dir(self.chrome_profile_dir)


def resolve_profile_dir(raw: str) -> Path:
    raw = raw.replace("~/.linkreach", str(paths.home()), 1) if raw.startswith("~/.linkreach") else raw
    return Path(os.path.expandvars(raw)).expanduser().resolve()


@dataclass
class Inputs:
    config: Config


def _fmt_pydantic(prefix: str, exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{prefix}: {loc}: {msg}")
    return out


def removed_key_problems(raw: dict) -> list[str]:
    return [
        f"config.yaml: {key}: removed setting ({why}); delete it from config.yaml"
        for key, why in REMOVED_KEYS.items()
        if key in raw
    ]


def load_inputs(directory: Path | None = None) -> Inputs:
    directory = directory or paths.inputs_dir()
    problems: list[str] = []

    cfg: Config | None = None
    cfg_path = directory / "config.yaml"
    if not cfg_path.exists():
        problems.append(f"config.yaml: not found in {directory} (run `linkreach init`)")
    else:
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                problems.append("config.yaml: top level must be a mapping")
            else:
                problems.extend(removed_key_problems(raw))
                current = {k: v for k, v in raw.items() if k not in REMOVED_KEYS}
                cfg = Config.model_validate(current)
        except yaml.YAMLError as exc:
            problems.append(f"config.yaml: YAML error: {exc}")
        except ValidationError as exc:
            problems.extend(_fmt_pydantic("config.yaml", exc))

    if problems:
        raise ConfigError(problems)
    assert cfg is not None
    return Inputs(config=cfg)
