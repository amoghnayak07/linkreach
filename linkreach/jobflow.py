"""The Job pipeline (ADR-0002: fixed steps in code, Claude only at set points).

`process_job` is the one function that does the work for a confirmed Job and its
confirmed Picks; `linkreach job` is a thin terminal wrapper around it, and a future
dashboard form can call it the same way. Per Pick: read the profile (within the page-view
caps and stop rules), ask the Email finder while the profile is open, draft, validate,
then `finish_pick` (save, Gmail draft, status). `redraft_pick` reuses that last step for
`needs_detail` Picks. Each Pick is committed as soon as it's done, so a stopped run keeps
its progress.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit

from linkreach import clock, logsetup, paths, sanitize, validate
from linkreach.commands.common import Ctx, FailStreak, linkedin_session
from linkreach.db import DB, normalize_profile_url
from linkreach.emailfinder import EmailFinder, NoFinder
from linkreach.gmail import GmailDrafts, GmailError
from linkreach.jobdraft import EmailDraft, JobDrafter, JobFields, PickFacts
from linkreach.jobsearch import FoundPick, SearchOutcome, find_picks
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


def _local_date(iso_ts: str) -> str:
    return clock.parse(iso_ts).astimezone().date().isoformat()


def contact_flags(db: DB, profile_url: str, exclude_job_id: int | None = None) -> list[str]:
    """Duplicate guard: one line per other Job on which this Person was already contacted
    (emailed or later), e.g. "already emailed on 2026-11-20 for Job #3 PM at Microsoft".
    Empty for a new Person. It only informs; the user decides whether to keep the Pick."""
    person_id = db.person_id_for(profile_url)
    if person_id is None:
        return []
    flags = []
    for r in db.prior_contacts(person_id, exclude_job_id):
        job = f"Job #{r['job_id']} {r['role_title'] or 'role'} at {r['company']}"
        if r["emailed_at"]:
            flags.append(f"already emailed on {_local_date(r['emailed_at'])} for {job}")
        else:
            flags.append(f"already contacted on {_local_date(r['contacted_at'])} for {job} (now {r['status']})")
    return flags


_SLUG_RE = re.compile(r"^[A-Za-z0-9_\-%.]{1,100}$")
_COMPANY_LINK_RE = re.compile(r"^(?:https?://)?(?:[a-z]+\.)?linkedin\.com/company/([^/?#\s]+)", re.I)


def guess_company_slug(company: str) -> str:
    """'Goldman Sachs' -> 'goldman-sachs'. Only ever offered for the user to confirm."""
    return re.sub(r"[^a-z0-9]+", "-", (company or "").lower()).strip("-")[:100]


def parse_company_page(text: str) -> str | None:
    """A company page link (or a bare slug) -> its slug, or None if it isn't one."""
    raw = (text or "").strip().strip("<>\"'")
    m = _COMPANY_LINK_RE.match(raw)
    slug = m.group(1) if m else raw
    return slug.lower() if _SLUG_RE.match(slug) and "/" not in slug else None


def company_page_url(slug: str) -> str:
    return f"https://www.linkedin.com/company/{slug}/"


def search_found_picks(
    ctx: Ctx, job: dict[str, Any], company_slug: str, need: int, exclude_urls: set[str], client: Any
) -> SearchOutcome:
    """Search LinkedIn for up to `need` Found picks. Opens the browser; page views count
    against the daily cap and the stop rules apply. Saves nothing about the Job itself."""
    with linkedin_session(ctx, COMMAND, f"search need={need}") as li:
        return find_picks(li, ctx.db, ctx.cfg, client, job, company_slug, need, exclude_urls)


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


def add_found_picks(db: DB, job_id: int, found: list[FoundPick]) -> list[int]:
    """Save confirmed Found picks with their tier and reason, after the Supplied ones."""
    job = db.get_job(job_id)
    assert job is not None
    ids = []
    for f in found:
        person_id = db.ensure_person(f.profile_url, name=f.name, company=job["company"], title=f.title, is_alumni=f.alumni)
        pick_id = db.add_pick(job_id, person_id, "found", tier=f.tier, reason=f.reason)
        if pick_id is not None:
            ids.append(pick_id)
    return ids


_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh", "group", "the"}


def _company_key(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return " ".join(w for w in words if w not in _COMPANY_SUFFIXES)


def company_mismatch(company: str, profile: Profile) -> bool:
    """True when the profile's headline and top card have text but don't mention the Job's
    company. A profile with no top-card text at all isn't flagged: there's nothing to go on."""
    key = _company_key(company)
    seen = " ".join(v for v in (profile.headline, profile.topcard) if v)
    if not key or not seen.strip():
        return False
    return f" {key} " not in f" {_company_key(seen)} "


@dataclass
class PickResult:
    pick_id: int
    name: str
    profile_url: str
    status: str  # drafted | no_email | needs_detail | picked (not finished)
    note: str = ""
    email_found: bool = False
    gmail_draft_id: str | None = None
    problem: str = ""  # why a Pick isn't drafted, or why its Gmail draft wasn't created
    warnings: list[str] = field(default_factory=list)  # shown, never blocking

    @property
    def gmail_pending(self) -> bool:
        """Validated and saved, but the Gmail draft failed: `linkreach redraft` retries it."""
        return bool(self.note) and self.status in RETRYABLE_STATUSES


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
    def needs_detail(self) -> int:
        return sum(1 for r in self.results if r.status == "needs_detail" and not r.gmail_pending)

    @property
    def failures(self) -> int:
        return len(self.results) - self.drafts - self.needs_detail

    @property
    def gmail_drafts(self) -> int:
        return sum(1 for r in self.results if r.gmail_draft_id)

    @property
    def emails_found(self) -> int:
        return sum(1 for r in self.results if r.email_found)


# ---------------------------------------------------------------- finishing a Pick

# Statuses a Pick can be in while its validated draft waits for a Gmail draft.
RETRYABLE_STATUSES = ("picked", "needs_detail")


def gmail_pending(row: Any) -> bool:
    """A Pick whose draft passed validation and has an email, but whose Gmail draft wasn't
    created (Gmail failed). Its subject, body, and note are saved; only Gmail is retried."""
    return (
        row["status"] in RETRYABLE_STATUSES
        and bool(row["email"])
        and bool(row["email_body"])
        and bool(row["connection_note"])
        and not row["gmail_draft_id"]
    )


@dataclass
class Finished:
    status: str  # drafted | no_email, or the unchanged status when Gmail failed
    gmail_draft_id: str | None = None
    gmail_error: str = ""  # short, content-free reason


def _gmail_reason(exc: Exception) -> str:
    # GmailError messages never hold draft content or tokens; anything else shows its type only.
    return str(exc)[:200] if isinstance(exc, GmailError) else type(exc).__name__


def finish_pick(ctx: Ctx, pick: Any, draft: EmailDraft, email: str | None, gmail: GmailDrafts) -> Finished:
    """The one path from a validated draft to a finished Pick, shared by `job` and
    `redraft`: save the subject, body, and note; with an email, create the Gmail draft and
    move to `drafted`; without one, move to `no_email` (no Gmail draft). If Gmail fails,
    the draft stays saved, the status doesn't move, and the failure is logged without
    content, so the Pick can be retried."""
    db = ctx.db
    pick_id, person_id = int(pick["id"]), int(pick["person_id"])
    fields: dict[str, Any] = {
        "email": email,
        "email_subject": draft.subject,
        "email_body": draft.body,
        "connection_note": draft.note,
        "validation_errors": "\n".join(draft.errors) or None,  # only "dropped from prompt" notes remain
    }
    if not email:
        db.set_pick_status(pick_id, "no_email", **fields)
        return Finished("no_email")
    try:
        draft_id = gmail.create_draft(email, draft.subject, draft.body)
    except Exception as exc:  # one Pick's Gmail failure never stops the run
        db.update_pick(pick_id, **fields)
        reason = _gmail_reason(exc)
        db.log(COMMAND, "info", person_id, f"pick {pick_id}: gmail draft failed ({type(exc).__name__})")
        logsetup.event(log, "gmail draft failed", pick_id=pick_id, error=type(exc).__name__)
        current = db.get_pick(pick_id)
        return Finished(current["status"] if current else str(pick["status"]), gmail_error=reason)
    db.set_pick_status(pick_id, "drafted", gmail_draft_id=draft_id, **fields)
    db.log(COMMAND, "info", person_id, f"pick {pick_id}: gmail draft created")
    logsetup.event(log, "gmail draft created", pick_id=pick_id)
    return Finished("drafted", gmail_draft_id=draft_id)


def _apply_finish(result: PickResult, fin: Finished, note: str) -> None:
    result.status = fin.status
    result.note = note
    result.gmail_draft_id = fin.gmail_draft_id
    if fin.gmail_error:
        result.problem = f"Gmail draft not created ({fin.gmail_error}); run `linkreach redraft` to retry"


def retry_gmail(ctx: Ctx, pick_id: int, gmail: GmailDrafts) -> PickResult:
    """Create the Gmail draft for a Pick whose saved draft is waiting on Gmail."""
    row = ctx.db.get_pick(pick_id)
    if row is None or not gmail_pending(row):
        raise ValueError(f"pick {pick_id} has no draft waiting for Gmail")
    result = PickResult(pick_id=pick_id, name=row["name"], profile_url=row["profile_url"], status=row["status"], email_found=True)
    draft = EmailDraft(status="ok", subject=row["email_subject"] or "", body=row["email_body"], note=row["connection_note"])
    if row["validation_errors"]:
        draft.errors = [e for e in str(row["validation_errors"]).splitlines() if e.startswith("dropped")]
    _apply_finish(result, finish_pick(ctx, row, draft, row["email"], gmail), draft.note)
    return result


def _draft_problem(draft: EmailDraft) -> str:
    return "; ".join(e for e in draft.errors if not e.startswith("dropped")) or "draft failed"


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
    gmail: GmailDrafts,
    finder: EmailFinder | None = None,
    on_pick: Callable[[PickResult], None] | None = None,
) -> JobReport:
    """Read, look up, draft, and save every `picked` Pick of a Job, creating a Gmail draft
    for each one with an email. Safety stops (CAPTCHA, caps, selector breaks) propagate to
    the caller; `report` keeps what was done before the stop."""
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
                result = _process_pick(ctx, li, streak, finder, drafter, gmail, job, p)
                report.results.append(result)
                if on_pick:
                    on_pick(result)
    finally:
        report.views_used = cap_status(db, cfg).views_today - views_before
    return report


def _process_pick(
    ctx: Ctx, li: Any, streak: FailStreak, finder: EmailFinder, drafter: JobDrafter, gmail: GmailDrafts, job: Any, p: Any
) -> PickResult:
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

    # Alumni from the profile's education, or already known (e.g. found by the alumni search).
    is_alumni = bool(p["is_alumni"]) or (bool(cfg.alumni_school) and cfg.alumni_school.lower() in profile.education.lower())
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
    if p["origin"] == "supplied" and company_mismatch(job["company"], profile):
        result.warnings.append(f"profile doesn't show {job['company']} as the current company (kept)")
        db.log(COMMAND, "info", person_id, f"pick {pick_id}: company mismatch warning")

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
    if draft is not None and draft.status == "failed":
        # Failed validation every attempt (or was refused): the user adds detail and redrafts.
        # The email is kept so the redraft needs no new Reveal; no Gmail draft is made.
        result.problem = _draft_problem(draft)
        db.set_pick_status(pick_id, "needs_detail", email=email, validation_errors=result.problem[:2000])
        db.log(COMMAND, "info", person_id, f"pick {pick_id}: needs_detail")
        logsetup.event(log, "pick needs detail", pick_id=pick_id, attempts=draft.attempts)
        result.status = "needs_detail"
        return result
    if draft is None or draft.status != "ok":
        if draft is not None:
            result.problem = _draft_problem(draft)
        db.update_pick(pick_id, email=email, validation_errors=result.problem[:2000])
        db.log(COMMAND, "info", person_id, f"pick {pick_id}: draft failed")
        return result

    fin = finish_pick(ctx, p, draft, email, gmail)
    db.log(COMMAND, "info", person_id, f"pick {pick_id}: {fin.status} via {found.source}")
    logsetup.event(log, "pick saved", pick_id=pick_id, status=fin.status, attempts=draft.attempts, finder=found.source)
    _apply_finish(result, fin, draft.note)
    if not email:
        result.problem = found.reason
    return result


# ---------------------------------------------------------------- needs_detail redraft

USER_DETAIL_CAP = 300


class BadDetail(ValueError):
    pass


def clean_user_detail(text: str) -> str:
    """The user's one line of context, sanitized like profile data. Text that looks like an
    instruction, or carries a URL or email address, is refused (it could only make the
    draft fail validation, or steer the model)."""
    detail = sanitize.clean_line(text, USER_DETAIL_CAP)
    reasons = validate.suspicious_context(detail)
    if reasons:
        raise BadDetail("leave out " + ", ".join({"instruction pattern": "instruction-like words", "url": "links", "email": "email addresses"}[r] for r in reasons))
    return detail


def facts_from_row(job: Any, row: Any, user_detail: str) -> PickFacts:
    """What the drafting prompt knows about a Pick from the database alone: no page view."""
    return PickFacts(
        name=row["name"],
        title=row["title"] or "",
        company=job["company"],
        is_alumni=bool(row["is_alumni"]),
        details=[d for d in (row["context_1"], row["context_2"]) if d],
        user_detail=user_detail,
    )


def redraft_pick(ctx: Ctx, pick_id: int, user_detail: str, client: Any, style: str, gmail: GmailDrafts) -> PickResult:
    """Redraft a `needs_detail` Pick with one line of the user's context, from what's saved
    (no browser, no Reveal). A draft that passes goes through `finish_pick`, like in `job`;
    one that fails again stays `needs_detail` with the new errors. `user_detail` must
    already be cleaned by `clean_user_detail`."""
    db = ctx.db
    row = db.get_pick(pick_id)
    if row is None or row["status"] != "needs_detail":
        raise ValueError(f"pick {pick_id} isn't needs_detail")
    job = db.get_job(int(row["job_id"]))
    assert job is not None
    db.update_pick(pick_id, user_detail=user_detail)
    result = PickResult(pick_id=pick_id, name=row["name"], profile_url=row["profile_url"], status="needs_detail",
                        email_found=bool(row["email"]))
    try:
        draft = JobDrafter(ctx.cfg, client, style).draft(job, facts_from_row(job, row, user_detail))
    except Exception as exc:
        draft = None
        result.problem = f"Claude call failed ({type(exc).__name__})"
        logsetup.event(log, "redraft failed", pick_id=pick_id, error=type(exc).__name__)
    if draft is None or draft.status != "ok":
        if draft is not None:
            result.problem = _draft_problem(draft)
        db.update_pick(pick_id, validation_errors=result.problem[:2000])
        db.log(COMMAND, "info", int(row["person_id"]), f"pick {pick_id}: redraft failed")
        return result
    _apply_finish(result, finish_pick(ctx, row, draft, row["email"], gmail), draft.note)
    db.log(COMMAND, "info", int(row["person_id"]), f"pick {pick_id}: redrafted, {result.status}")
    return result
