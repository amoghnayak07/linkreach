"""LinkedIn page logic on top of a `browser.Session`.

Every page load goes through `LinkedIn.visit`, which:
1. checks the daily view cap,
2. waits a random 8 to 25 seconds after the previous load,
3. loads the page and checks the domain allowlist,
4. writes a `view` event to the activity log,
5. stops the run on any CAPTCHA, security check, or warning.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote_plus, unquote, urlsplit

from linkreach import logsetup, sanitize
from linkreach import selectors as S
from linkreach.browser import Session
from linkreach.config import Config
from linkreach.db import DB, normalize_profile_url
from linkreach.safety import StopRun, check_view_cap

log = logsetup.get("linkedin")
_rng = random.SystemRandom()


@dataclass
class Candidate:
    name: str
    title: str
    profile_url: str


@dataclass
class Profile:
    ok: bool
    name: str = ""
    headline: str = ""
    about: str = ""
    featured: str = ""
    education: str = ""
    topcard: str = ""
    first_degree: bool = False
    pending: bool = False
    has_actions: bool = False
    missing: list[str] = field(default_factory=list)


@dataclass
class ConnectResult:
    outcome: str  # sent | failed | skipped | already_pending | already_connected
    reason: str = ""


class LinkedIn:
    def __init__(
        self,
        session: Session,
        db: DB,
        cfg: Config,
        command: str,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.s = session
        self.db = db
        self.cfg = cfg
        self.command = command
        self.sleep = sleep
        self._loaded_once = False
        self._company_ids: dict[str, str | None] = {}
        self._company_sizes: dict[str, int | None] = {}

    # ---------- navigation ----------
    def visit(self, url: str, person_id: int | None = None) -> None:
        check_view_cap(self.db, self.cfg)
        if self._loaded_once:
            self.sleep(_rng.uniform(self.cfg.delay.min_seconds, self.cfg.delay.max_seconds))
        self._loaded_once = True
        self.s.goto(url)
        self.db.log(self.command, "view", person_id, _url_for_log(url))
        self.detect_stop()

    def detect_stop(self) -> None:
        url = (self.s.url or "").lower()
        for kind, parts in S.STOP_URL_PARTS.items():
            for part in parts:
                if part in url:
                    self._stop(kind, f"url matched {part!r}")
        for kind, sels in S.STOP_SELECTORS.items():
            if self.s.exists(sels):
                self._stop(kind, "page element matched")
        body = (self.s.body_text() or "").lower().replace("’", "'")
        for kind, phrases in S.STOP_PHRASES.items():
            for phrase in phrases:
                if phrase in body:
                    self._stop(kind, f"page text matched {phrase!r}")

    def _stop(self, kind: str, detail: str) -> None:
        event = "captcha" if kind == "captcha" else "stop"
        self.db.log(self.command, event, None, f"{kind}: {detail}")
        logsetup.event(log, "run stopped by LinkedIn page", kind=kind, detail=detail, command=self.command)
        raise StopRun(kind, detail)

    # ---------- login ----------
    def logged_in(self) -> bool:
        self.visit(S.FEED_URL)
        url = (self.s.url or "").lower()
        if any(p in url for p in S.LOGGED_OUT_URL_PARTS):
            return False
        return self.s.exists(S.LOGGED_IN_MARKERS, timeout_ms=5000)

    # ---------- search ----------
    def company_id(self, company_slug: str) -> str | None:
        """Numeric company id. Read from the company's People tab once (one page view), then
        cached in the database for 90 days."""
        return self.company_info(company_slug)[0]

    def company_info(self, company_slug: str) -> tuple[str | None, int | None]:
        """(numeric company id, employee count). Both come from the one People-tab view the id
        lookup needs; either is None when it can't be read. Cached together for 90 days."""
        if company_slug not in self._company_ids:
            cid = self.db.get_company_id(company_slug)
            size = self.db.get_company_size(company_slug) if cid else None
            if cid is None:
                self.visit(S.COMPANY_PEOPLE_URL.format(slug=quote_plus(company_slug), keywords=""))
                cid = parse_company_id(self.s.attr(S.COMPANY_ID_LINK, "href", timeout_ms=8000))
                size = parse_company_size(self.s.body_text() or "")
                if cid:
                    self.db.set_company_id(company_slug, cid, size)
            self._company_ids[company_slug] = cid
            self._company_sizes[company_slug] = size
        return self._company_ids[company_slug], self._company_sizes.get(company_slug)

    def search_company_people(self, company_slug: str, keywords: str) -> list[Candidate]:
        cid = self.company_id(company_slug)
        if cid:
            self.visit(S.PEOPLE_SEARCH_URL.format(keywords=quote_plus(keywords), company_id=cid))
        else:
            # Older UI: the People tab filtered by ?keywords= itself.
            self.visit(S.COMPANY_PEOPLE_URL.format(slug=quote_plus(company_slug), keywords=quote_plus(keywords)))
        self.s.exists(S.PEOPLE_CARD, timeout_ms=8000)
        out: list[Candidate] = []
        for rec in self.s.cards(S.PEOPLE_CARD, S.PEOPLE_CARD_FIELDS):
            href = rec.get("url", "")
            if "/in/" not in href:
                continue  # "LinkedIn Member" cards without a public profile
            name = sanitize.clean_line(rec.get("name", ""), 120)
            if not name or name.lower() == "linkedin member":
                continue
            out.append(
                Candidate(
                    name=name,
                    title=sanitize.clean_line(current_role(rec.get("snippet", "")) or rec.get("title", ""), 200),
                    profile_url=normalize_profile_url(href),
                )
            )
        return out

    # ---------- profile ----------
    def read_profile(self, url: str, person_id: int | None = None) -> Profile:
        self.visit(url, person_id)
        name = self.s.text(S.PROFILE_NAME, timeout_ms=8000)
        p = Profile(ok=False)
        if not name:
            p.missing.append("PROFILE_NAME")
        p.has_actions = self.s.exists(S.PROFILE_ACTIONS, timeout_ms=3000)
        if not p.has_actions:
            p.missing.append("PROFILE_ACTIONS")
        p.name = sanitize.clean_line(name or "", 120)
        paras = self.s.texts(S.PROFILE_TOPCARD_PARAS)
        p.headline = sanitize.clean(self.s.text(S.PROFILE_HEADLINE) or pick_headline(paras, name or ""))
        # The top card's lines include the current company; `job` checks Supplied picks against it.
        p.topcard = sanitize.clean(" | ".join(paras[:12]), 1000)
        p.about = sanitize.clean(self.s.text(S.PROFILE_ABOUT) or "")
        feats = [t for t in self.s.texts(S.PROFILE_FEATURED) if len(t.strip()) > 20] or self.s.texts(S.PROFILE_FEATURED)
        p.featured = sanitize.clean(feats[0] if feats else "")
        edu = self.s.texts(S.PROFILE_EDUCATION)[:12] + self.s.texts(S.PROFILE_HIGHLIGHTS)[:6]
        p.education = sanitize.clean(" | ".join(edu), 1000)
        degree = (self.s.text(S.PROFILE_DEGREE) or "").lower()
        p.pending = self.s.exists(S.PENDING_STATE)
        # The new top card carries a hidden "· 1st" template line, so also require that there is
        # no Connect for this person and no pending invite: a 1st-degree connection has neither.
        slug = profile_slug(self.s.url)
        own = [sel.format(slug=slug) for sel in S.CONNECT_FOR_SLUG] if slug else []
        can_connect = self.s.exists(own + S.CONNECT_BUTTON)
        p.first_degree = "1st" in degree and not can_connect and not p.pending
        p.ok = not p.missing
        return p

    # ---------- connect ----------
    def open_connect_dialog(self) -> ConnectResult | None:
        """Click Connect (or More > Connect) and then 'Add a note'.
        Returns a ConnectResult on failure, None when the note box is ready."""
        if self.s.exists(S.PENDING_STATE):
            return ConnectResult("already_pending")
        # Only this profile's own Connect: the invite link carrying its vanity name first, then
        # top-card-scoped fallbacks. Never a page-wide "Invite X to connect" (other people's).
        slug = profile_slug(self.s.url)
        own = [sel.format(slug=slug) for sel in S.CONNECT_FOR_SLUG] if slug else []
        if not self.s.click(own + S.CONNECT_BUTTON, timeout_ms=3000):
            if not self.s.click(S.MORE_BUTTON, timeout_ms=3000):
                return ConnectResult("failed", "no Connect or More button")
            if not self.s.click(S.MORE_MENU_CONNECT, timeout_ms=3000):
                self.s.press("Escape")
                return ConnectResult("failed", "no Connect option under More")
        self.detect_stop()
        if self.s.exists(S.EMAIL_REQUIRED, timeout_ms=1500):
            self._dismiss()
            return ConnectResult("failed", "LinkedIn asked for their email address")
        if not self.s.click(S.ADD_NOTE_BUTTON, timeout_ms=5000):
            self._dismiss()
            return ConnectResult("failed", "no 'Add a note' button")
        if not self.s.exists(S.NOTE_TEXTAREA, timeout_ms=5000):
            self._dismiss()
            return ConnectResult("failed", "note box did not appear")
        return None

    def type_note(self, note: str) -> bool:
        return self.s.fill(S.NOTE_TEXTAREA, note)

    def click_send(self) -> bool:
        return self.s.click(S.SEND_BUTTON, timeout_ms=5000)

    def confirm_pending(self, timeout_ms: int = 10000) -> bool:
        ok = self.s.exists(S.PENDING_STATE, timeout_ms=timeout_ms)
        self.detect_stop()
        return ok

    def _dismiss(self) -> None:
        if not self.s.click(S.DIALOG_DISMISS, timeout_ms=1500):
            self.s.press("Escape")


def _url_for_log(url: str) -> str:
    # Keep only the path; no query strings in the activity log.
    return url.split("?", 1)[0][:300]


_SLUG_RE = re.compile(r"[A-Za-z0-9%_.-]{1,150}")
_DEGREE_RE = re.compile(r"^\W*(1st|2nd|3rd)", re.I)
_PRONOUNS_RE = re.compile(r"^[A-Za-z]+/[A-Za-z]+(/[A-Za-z]+)?$")


def profile_slug(url: str) -> str | None:
    """Vanity name from /in/<slug>/, only if it is safe to put inside a CSS attribute value."""
    m = re.search(r"/in/([^/?#]+)", urlsplit(url or "").path)
    if not m:
        return None
    slug = m.group(1)
    return slug if _SLUG_RE.fullmatch(slug) else None


def parse_company_id(href: str | None) -> str | None:
    """'...currentCompany=%5B%221035%22%5D...' -> '1035'."""
    m = re.search(r'currentCompany=\["?(\d+)', unquote(href or ""))
    return m.group(1) if m else None


_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*([KkMm])?"
_EMPLOYEES_RE = re.compile(_NUM + r"\s*(?:\+|[-–]\s*" + _NUM + r")?\s+employees\b", re.I)
_MEMBERS_RE = re.compile(_NUM + r"\s+associated members\b", re.I)


def _count(num: str, suffix: str | None) -> int:
    value = float(num.replace(",", ""))
    mult = {"k": 1_000, "m": 1_000_000}.get((suffix or "").lower(), 1)
    return int(value * mult)


def parse_company_size(text: str) -> int | None:
    """Employee count from a company page's text. A range counts as its upper end:
    '51-200 employees' -> 200, '1,001-5,000 employees' -> 5000, '10K+ employees' -> 10000.
    Falls back to the People tab's '2,345 associated members'. None if neither is there."""
    m = _EMPLOYEES_RE.search(text or "")
    if m:
        lo, lo_sfx, hi, hi_sfx = m.groups()
        return _count(hi, hi_sfx) if hi else _count(lo, lo_sfx)
    m = _MEMBERS_RE.search(text or "")
    return _count(*m.groups()) if m else None


def pick_headline(paragraphs: list[str], name: str) -> str:
    """The new top card has no hook for the headline: it is the first line that is not
    pronouns, the name, or the '· 2nd' degree marker."""
    for t in paragraphs:
        t = (t or "").strip()
        if len(t) < 3 or t == name or _DEGREE_RE.match(t) or _PRONOUNS_RE.match(t):
            continue
        return t
    return ""


def current_role(snippet: str) -> str:
    """'Current: Senior Technical Recruiter at Microsoft' -> 'Senior Technical Recruiter at Microsoft'.
    Past roles are ignored so someone who *used to* recruit is not bucketed as a recruiter."""
    t = " ".join((snippet or "").split())
    return t[len("current:"):].strip() if t.lower().startswith("current:") else ""
