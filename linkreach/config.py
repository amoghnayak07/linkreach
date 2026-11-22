"""Load and validate config.yaml, companies.csv, and jobs.csv with Pydantic.

All problems across all three files are collected and reported together, so
one run shows every fix you need to make.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
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

DEFAULT_BANNED_PHRASES = [
    "synergy",
    "leverage",
    "passionate about disrupting",
    "circle back",
    "i hope this finds you well",
]

DEFAULT_EXCLUDES = ["intern", "associate", "coordinator", "assistant", "freelance"]

COMPANY_URL_RE = re.compile(r"^https://(www\.)?linkedin\.com/company/[A-Za-z0-9_\-%.]+/?$")
PROFILE_URL_RE = re.compile(r"^https://(www\.)?linkedin\.com/in/[A-Za-z0-9_\-%.]+/?$")

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


class Bucket(Strict):
    keywords: list[str] = Field(min_length=1)
    angle: str = Field(min_length=1)


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


class Templates(Strict):
    note: str
    followup: str
    role_with_job: str
    role_without_job: str
    email_subject: str

    @field_validator("note")
    @classmethod
    def _note_fields(cls, v: str) -> str:
        for name in ("{first_name}", "{opener}", "{tie_line}"):
            if name not in v:
                raise ValueError(f"templates.note must contain {name}")
        return v

    @field_validator("followup")
    @classmethod
    def _followup_fields(cls, v: str) -> str:
        for name in ("{first_name}", "{opener}", "{role_sentence}", "{point1}", "{point2}", "{resume_url}"):
            if name not in v:
                raise ValueError(f"templates.followup must contain {name}")
        return v


ConnectMode = Literal["manual", "automated"]


class Config(Strict):
    # ADR-0001: automated connection requests are off unless this is "automated".
    connect_mode: ConnectMode = "manual"
    caps: Caps = Caps()
    per_company_limit: int = Field(6, ge=1, le=50)
    combine_keywords: bool = True  # one search per bucket ("a" OR "b") instead of one per keyword
    delay: Delay = Delay()
    buckets: dict[str, Bucket]
    alumni_school: str = "Northeastern"
    alumni_angle: str = "Lead with Northeastern, highest priority"
    exclude_title_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    background: str = Field(min_length=20)
    resume_url: str
    banned_phrases: list[str] = Field(default_factory=lambda: list(DEFAULT_BANNED_PHRASES))
    model: str = "claude-sonnet-5-5"
    use_refusal_fallbacks: bool = True
    # Connection note limit: 200 for a free LinkedIn account, 300 with Premium.
    note_max_chars: int = Field(200, ge=50, le=300)
    followup_max_words: int = Field(150, ge=50, le=400)
    follow_up_delay_days: int = Field(5, ge=1)
    brake: Brake = Brake()
    auto_window: AutoWindow = AutoWindow()
    chrome_profile_dir: str = "~/.linkreach/chrome-profile"
    chrome_channel: str = "chrome"
    headless: bool = False
    doctor_profile_url: str
    templates: Templates

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

    @field_validator("buckets")
    @classmethod
    def _buckets(cls, v: dict[str, Bucket]) -> dict[str, Bucket]:
        if not v:
            raise ValueError("at least one bucket is required")
        for name in v:
            if not re.match(r"^[a-z][a-z0-9_]*$", name):
                raise ValueError(f"bucket name {name!r} must be lowercase letters, digits, underscores")
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


class Company(Strict):
    company_name: str = Field(min_length=1)
    linkedin_company_url: str
    priority: int = Field(ge=1, le=3)

    @field_validator("company_name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company_name is empty")
        return v

    @field_validator("linkedin_company_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not COMPANY_URL_RE.match(v):
            raise ValueError("must look like https://www.linkedin.com/company/<slug>/")
        return v.rstrip("/") + "/"

    @property
    def slug(self) -> str:
        return self.linkedin_company_url.rstrip("/").rsplit("/", 1)[-1]


class Job(Strict):
    company_name: str = Field(min_length=1)
    job_title: str = Field(min_length=1)
    job_url: str

    @field_validator("job_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^https://\S+$", v):
            raise ValueError("job_url must be an https:// URL")
        return v


@dataclass
class Inputs:
    config: Config
    companies: list[Company]
    jobs: dict[str, Job] = field(default_factory=dict)

    def company(self, name: str) -> Company | None:
        for c in self.companies:
            if c.company_name.lower() == name.lower():
                return c
        return None

    def priority_of(self, name: str) -> int:
        c = self.company(name)
        return c.priority if c else 9

    def job_for(self, company: str) -> Job | None:
        return self.jobs.get(company.lower())


def _fmt_pydantic(prefix: str, exc: ValidationError) -> list[str]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{prefix}: {loc}: {msg}")
    return out


def _read_csv(path: Path, required: list[str], label: str, problems: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, skipinitialspace=True)
        headers = [h.strip() for h in (reader.fieldnames or [])]
        missing = [r for r in required if r not in headers]
        if missing:
            problems.append(f"{label}: missing required column(s): {', '.join(missing)}")
            return []
        rows = []
        for row in reader:
            clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if not any(clean.values()):
                continue
            rows.append(clean)
        return rows


def load_inputs(directory: Path | None = None, require_csvs: bool = True) -> Inputs:
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
                cfg = Config.model_validate(raw)
        except yaml.YAMLError as exc:
            problems.append(f"config.yaml: YAML error: {exc}")
        except ValidationError as exc:
            problems.extend(_fmt_pydantic("config.yaml", exc))

    companies: list[Company] = []
    comp_path = directory / "companies.csv"
    if not comp_path.exists():
        if require_csvs:
            problems.append(f"companies.csv: not found in {directory}")
    else:
        rows = _read_csv(comp_path, ["company_name", "linkedin_company_url", "priority"], "companies.csv", problems)
        seen: set[str] = set()
        for i, row in enumerate(rows, start=2):
            try:
                c = Company.model_validate(
                    {k: row.get(k, "") for k in ("company_name", "linkedin_company_url", "priority")}
                )
                if c.company_name.lower() in seen:
                    problems.append(f"companies.csv: line {i}: duplicate company {c.company_name!r}")
                seen.add(c.company_name.lower())
                companies.append(c)
            except ValidationError as exc:
                problems.extend(_fmt_pydantic(f"companies.csv: line {i}", exc))
        if require_csvs and not rows and not any(p.startswith("companies.csv") for p in problems):
            problems.append("companies.csv: no companies listed")

    jobs: dict[str, Job] = {}
    jobs_path = directory / "jobs.csv"
    if jobs_path.exists():
        rows = _read_csv(jobs_path, ["company_name", "job_title", "job_url"], "jobs.csv", problems)
        known = {c.company_name.lower() for c in companies}
        for i, row in enumerate(rows, start=2):
            try:
                j = Job.model_validate({k: row.get(k, "") for k in ("company_name", "job_title", "job_url")})
                if known and j.company_name.lower() not in known:
                    problems.append(f"jobs.csv: line {i}: company {j.company_name!r} is not in companies.csv")
                jobs[j.company_name.lower()] = j
            except ValidationError as exc:
                problems.extend(_fmt_pydantic(f"jobs.csv: line {i}", exc))

    if problems:
        raise ConfigError(problems)
    assert cfg is not None
    companies.sort(key=lambda c: (c.priority, c.company_name.lower()))
    return Inputs(config=cfg, companies=companies, jobs=jobs)
