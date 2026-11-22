"""The Job pipeline (ADR-0002: fixed steps in code, Claude only at set points).

`process_job` is the one function that does the work for a confirmed Job and its
confirmed Picks; `linkreach job` is a thin terminal wrapper around it, and a future
dashboard form can call it the same way. Per Pick: read the profile (within the page-view
caps and stop rules), ask the Email finder while the profile is open, draft, validate,
save. Each Pick is committed as soon as it's done, so a stopped run keeps its progress.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from linkreach import logsetup, paths, sanitize, validate
from linkreach.commands.common import Ctx, FailStreak, linkedin_session
from linkreach.db import DB, normalize_profile_url
from linkreach.emailfinder import EmailFinder, NoFinder
from linkreach.jobdraft import JobDrafter, JobFields, PickFacts
from linkreach.linkedin import Profile
from linkreach.safety import cap_status

log = logsetup.get("job")
COMMAND = "job"

_PROFILE_RE = re.compile(r"^https://www\.linkedin\.com/in/[A-Za-z0-9_\-%.]+/$")


class StyleMissing(Exception):
    pass


def load_style() -> str:
    path = paths.style_path()
    if not path.exists():
        raise StyleMissing(f"no Style file at {path} (run `linkreach init` to create one from the example)")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise StyleMissing(f"the Style file at {path} is empty")
    return text


def parse_profile_link(raw: str) -> str | None:
    """A pasted profile link in canonical form, or None if it isn't a LinkedIn profile."""
    raw = raw.strip().strip("<>\"'")
    if not raw:
        return None
    if not raw.lower().startswith(("http://", "https://")):
        raw = "https://" + raw
    host = (urlsplit(raw).hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return None
    url = normalize_profile_url(raw)
    return url if _PROFILE_RE.match(url) else None


def split_links(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", text or "") if t]


def create_job(db: DB, fields: JobFields, description: str) -> int:
    return db.add_job(
        company=fields.company,
        description=description,
        role_title=fields.role_title,
        team=fields.team,
        location=fields.location,
    )


def add_supplied_picks(db: DB, job_id: int, urls: list[str]) -> list[int]:
    """Save confirmed Supplied picks. A Person already in the database is reused."""
    job = db.get_job(job_id)
    assert job is not None
    ids = []
    for url in urls:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        person_id = db.ensure_person(url, name=slug, company=job["company"])
        pick_id = db.add_pick(job_id, person_id, "supplied")
        if pick_id is not None:
            ids.append(pick_id)
    return ids


@dataclass
class PickResult:
    pick_id: int
    name: str
    profile_url: str
    status: str  # drafted | no_email | picked (not finished)
    note: str = ""
    email_found: bool = False
    problem: str = ""  # why a Pick isn't drafted


@dataclass
class JobReport:
    job_id: int
    results: list[PickResult] = field(default_factory=list)
    picks_total: int = 0
    views_used: int = 0

    @property
    def drafts(self) -> int:
        return sum(1 for r in self.results if r.status in ("drafted", "no_email"))

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.status not in ("drafted", "no_email"))

    @property
    def emails_found(self) -> int:
        return sum(1 for r in self.results if r.email_found)


def _details(profile: Profile) -> list[str]:
    return [v for v in (profile.about, profile.featured, profile.headline) if v]


def _plausible_email(value: str | None) -> str | None:
    value = (value or "").strip()
    return value if value and validate.EMAIL_RE.fullmatch(value) else None


def process_job(
    ctx: Ctx,
    job_id: int,
    report: JobReport,
    client: Any,
    style: str,
    finder: EmailFinder | None = None,
    on_pick: Callable[[PickResult], None] | None = None,
) -> JobReport:
    """Read, look up, draft, and save every `picked` Pick of a Job. Safety stops
    (CAPTCHA, caps, selector breaks) propagate to the caller; `report` keeps what was
    done before the stop."""
    db, cfg = ctx.db, ctx.cfg
    finder = finder or NoFinder()
    drafter = JobDrafter(cfg, client, style)
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"no job with id {job_id}")
    picks = db.picks(job_id, ["picked"])
    report.picks_total = len(picks)
    if not picks:
        return report
    views_before = cap_status(db, cfg).views_today
    try:
        with linkedin_session(ctx, COMMAND, f"start job={job_id} picks={len(picks)}") as li:
            streak = FailStreak(li, COMMAND)
            for p in picks:
                result = _process_pick(ctx, li, streak, finder, drafter, job, p)
                report.results.append(result)
                if on_pick:
                    on_pick(result)
    finally:
        report.views_used = cap_status(db, cfg).views_today - views_before
    return report


def _process_pick(ctx: Ctx, li: Any, streak: FailStreak, finder: EmailFinder, drafter: JobDrafter, job: Any, p: Any) -> PickResult:
    db, cfg = ctx.db, ctx.cfg
    pick_id, person_id = int(p["id"]), int(p["person_id"])
    result = PickResult(pick_id=pick_id, name=p["name"], profile_url=p["profile_url"], status="picked")

    profile = li.read_profile(p["profile_url"], person_id)
    if not profile.ok:
        streak.fail(person_id, profile.missing)  # raises after 3 in a row
        result.problem = "profile could not be read (missing " + ", ".join(profile.missing) + ")"
        db.update_pick(pick_id, validation_errors=result.problem)
        return result
    streak.ok()

    is_alumni = bool(cfg.alumni_school) and cfg.alumni_school.lower() in profile.education.lower()
    details = _details(profile)
    db.update_fields(
        person_id,
        name=profile.name or p["name"],
        title=sanitize.clean_line(profile.headline, 200) or p["title"],
        is_alumni=1 if is_alumni else 0,
        context_1=details[0] if details else None,
        context_2=details[1] if len(details) > 1 else None,
    )
    result.name = profile.name or p["name"]

    found = finder.find(li, profile)
    email = _plausible_email(found.email)
    result.email_found = email is not None

    facts = PickFacts(
        name=result.name,
        title=profile.headline,
        company=job["company"],
        is_alumni=is_alumni,
        details=details,
        user_detail=p["user_detail"] or "",
    )
    try:
        draft = drafter.draft(job, facts)
    except Exception as exc:  # API errors after SDK retries, network, etc.
        draft = None
        result.problem = f"Claude call failed ({type(exc).__name__})"
        logsetup.event(log, "draft failed", pick_id=pick_id, error=type(exc).__name__)
    if draft is None or draft.status != "ok":
        if draft is not None:
            result.problem = "; ".join(e for e in draft.errors if not e.startswith("dropped")) or "draft failed"
        db.update_pick(pick_id, validation_errors=result.problem[:2000])
        db.log(COMMAND, "info", person_id, f"pick {pick_id}: draft failed")
        return result

    status = "drafted" if email else "no_email"
    db.set_pick_status(
        pick_id,
        status,
        email=email,
        email_subject=draft.subject,
        email_body=draft.body,
        connection_note=draft.note,
        validation_errors="\n".join(draft.errors) or None,
    )
    db.log(COMMAND, "info", person_id, f"pick {pick_id}: {status} via {found.source}")
    logsetup.event(log, "pick saved", pick_id=pick_id, status=status, attempts=draft.attempts, finder=found.source)
    result.status = status
    result.note = draft.note
    if not email:
        result.problem = found.reason
    return result
