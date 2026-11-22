"""Fake browser and fake Claude client for tests. No network, no Chrome."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from linkreach import selectors as S
from linkreach.browser import _as_list, host_allowed
from linkreach.safety import DomainViolation


class FakePage:
    def __init__(self, url: str, body: str = "", elements: dict[str, str] | None = None, cards: list[dict] | None = None,
                 attrs: dict[str, dict[str, str]] | None = None):
        self.url = url
        self.body = body
        self.elements: dict[str, str] = dict(elements or {})
        self.card_list = cards or []
        self.attrs: dict[str, dict[str, str]] = dict(attrs or {})

    def visible(self) -> dict[str, str]:
        return self.elements

    def click(self, sel: str, session: "FakeSession") -> bool:
        return sel in self.visible()

    def fill(self, sel: str, value: str) -> bool:
        return sel in self.visible()

    def press(self, key: str) -> None:
        pass


class ProfilePage(FakePage):
    """A profile with a working connect flow. Tracks Send clicks."""

    def __init__(
        self,
        url: str,
        name: str,
        headline: str = "",
        about: str = "",
        education: str = "",
        connect: bool = True,
        pending: bool = False,
        first_degree: bool = False,
        broken: bool = False,
        pending_after_send: bool = True,
        send_effect: Callable[[], None] | None = None,
    ):
        super().__init__(url)
        self.name = name
        self.headline = headline
        self.about = about
        self.education = education
        self.connect = connect
        self.pending = pending
        self.first_degree = first_degree
        self.broken = broken
        self.pending_after_send = pending_after_send
        self.send_effect = send_effect
        self.dialog = None  # None | "connect" | "note"
        self.typed = ""
        self.send_clicks = 0

    def visible(self) -> dict[str, str]:
        if self.broken:
            return {}
        e: dict[str, str] = {S.PROFILE_NAME[0]: self.name}
        if self.headline:
            e[S.PROFILE_HEADLINE[0]] = self.headline
        if self.about:
            e[S.PROFILE_ABOUT[0]] = self.about
        if self.education:
            e[S.PROFILE_EDUCATION[0]] = self.education
        e[S.PROFILE_DEGREE[0]] = "· 1st" if self.first_degree else "· 2nd"
        e[S.PROFILE_ACTIONS[1]] = "More"
        e[S.MORE_BUTTON[0]] = "More"
        if self.pending:
            e[S.PENDING_STATE[0]] = "Pending"
        elif self.connect and not self.first_degree:
            e[S.CONNECT_BUTTON[0]] = "Connect"
        if self.dialog == "connect":
            e[S.ADD_NOTE_BUTTON[0]] = "Add a note"
            e[S.DIALOG_DISMISS[0]] = "Dismiss"
        if self.dialog == "note":
            e[S.NOTE_TEXTAREA[0]] = self.typed
            e[S.SEND_BUTTON[0]] = "Send"
            e[S.DIALOG_DISMISS[0]] = "Dismiss"
        return e

    def click(self, sel: str, session: "FakeSession") -> bool:
        if sel not in self.visible():
            return False
        if sel == S.CONNECT_BUTTON[0]:
            self.dialog = "connect"
        elif sel == S.ADD_NOTE_BUTTON[0]:
            self.dialog = "note"
        elif sel == S.DIALOG_DISMISS[0]:
            self.dialog = None
        elif sel == S.SEND_BUTTON[0]:
            self.send_clicks += 1
            session.total_send_clicks += 1
            self.dialog = None
            if self.pending_after_send:
                self.pending = True
            if self.send_effect:
                self.send_effect()
        return True

    def fill(self, sel: str, value: str) -> bool:
        if sel == S.NOTE_TEXTAREA[0] and self.dialog == "note":
            self.typed = value
            return True
        return False

    def press(self, key: str) -> None:
        if key == "Escape":
            self.dialog = None


class FakeSession:
    def __init__(self, pages: dict[str, FakePage] | None = None, default: FakePage | None = None):
        self.pages = pages or {}
        self.default = default
        self.current: FakePage = FakePage("about:blank")
        self.visits: list[str] = []
        self.total_send_clicks = 0
        self.screenshots: list[Path] = []
        self.closed = False

    def add(self, page: FakePage) -> FakePage:
        self.pages[page.url.split("?")[0]] = page
        return page

    @property
    def url(self) -> str:
        return self.current.url

    def goto(self, url: str) -> None:
        if not host_allowed(url):
            raise DomainViolation(f"refusing to open non-LinkedIn URL: {url}")
        self.visits.append(url)
        key = url.split("?")[0]
        page = self.pages.get(key) or self.default
        if page is None:
            page = FakePage(url, body="Page not found")
        self.current = page
        if not host_allowed(page.url):
            raise DomainViolation(f"navigation to a non-LinkedIn domain: {page.url}")

    def _match(self, selector) -> str | None:
        vis = self.current.visible()
        for s in _as_list(selector):
            if s in vis:
                return s
        return None

    def exists(self, selector, timeout_ms: int = 0) -> bool:
        return self._match(selector) is not None

    def text(self, selector, timeout_ms: int = 0) -> str | None:
        s = self._match(selector)
        return None if s is None else self.current.visible()[s]

    def texts(self, selector) -> list[str]:
        t = self.text(selector)
        return [t] if t else []

    def cards(self, card, fields) -> list[dict[str, str]]:
        return [dict(c) for c in self.current.card_list]

    def attr(self, selector, name: str, timeout_ms: int = 0) -> str | None:
        for s in _as_list(selector):
            if s in self.current.attrs:
                return self.current.attrs[s].get(name)
        return None

    def click(self, selector, timeout_ms: int = 5000) -> bool:
        s = self._match(selector)
        return False if s is None else self.current.click(s, self)

    def fill(self, selector, value: str, timeout_ms: int = 5000) -> bool:
        s = self._match(selector)
        return False if s is None else self.current.fill(s, value)

    def press(self, key: str) -> None:
        self.current.press(key)

    def body_text(self) -> str:
        return self.current.body

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fakepng")
        self.screenshots.append(path)

    def check_domain(self) -> None:
        if not host_allowed(self.current.url):
            raise DomainViolation(self.current.url)

    def close(self) -> None:
        self.closed = True


def feed_page(logged_in: bool = True) -> FakePage:
    if logged_in:
        return FakePage(S.FEED_URL, body="Home feed", elements={S.LOGGED_IN_MARKERS[0]: "nav"})
    return FakePage("https://www.linkedin.com/login", body="Sign in")


def search_page(slug: str, people: list[tuple[str, str, str]]) -> FakePage:
    """people: (name, title, profile_url)"""
    url = f"https://www.linkedin.com/company/{slug}/people/"
    cards = [{"name": n, "title": t, "url": u} for n, t, u in people]
    return FakePage(url, body="People", elements={S.PEOPLE_CARD[0]: "card"} if cards else {}, cards=cards)


def company_page(slug: str, company_id: str) -> FakePage:
    """New-UI People tab: ignores keywords, but links carry the numeric company id."""
    href = f"https://www.linkedin.com/search/results/people/?currentCompany=%5B%22{company_id}%22%5D&origin=X"
    return FakePage(f"https://www.linkedin.com/company/{slug}/people/", body="People", attrs={S.COMPANY_ID_LINK[0]: {"href": href}})


def people_search_page(company_id: str, people: list[tuple[str, str, str]]) -> FakePage:
    url = "https://www.linkedin.com/search/results/people/"
    cards = [{"name": n, "title": t, "url": u} for n, t, u in people]
    return FakePage(url, body="Results", elements={S.PEOPLE_CARD[0]: "card"} if cards else {}, cards=cards)


def captcha_page(url: str) -> FakePage:
    return FakePage(url, body="Let's do a quick security check. Please verify you're a human.")


# ---------------- fake Claude ----------------
GOOD_PARTS = {
    "has_specific_detail": True,
    "note_opener": "Your Azure onboarding post made YAML sound almost fun, which is a rare magic trick.",
    "note_tie_line": "I ran AI rollouts across 15+ enterprise clients at Bizom.",
    "followup_opener": "Anyone who can make cloud onboarding feel brisk deserves a medal.",
    "point1": "AI platform delivery: I shipped an image-recognition module that lifted conversion 25%.",
    "point2": "Enterprise scale: your team's push into regulated industries matches my ERP work.",
}


class FakeClaude:
    def __init__(self, responder: Callable[[dict], dict] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.responder = responder or (lambda kw: dict(GOOD_PARTS))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        parts = self.responder(kw)
        return SimpleNamespace(
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(parts))],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=100, cache_read_input_tokens=50, cache_creation_input_tokens=0, output_tokens=40),
        )

    def user_text(self, i: int = -1) -> str:
        return self.calls[i]["messages"][0]["content"]

    def calls_for(self, kind: str) -> list[dict[str, Any]]:
        """Calls of one kind in the Job flow: "extract" or "email"."""
        return [kw for kw in self.calls if request_kind(kw) == kind]


# ---------------- fake Claude for the Job flow ----------------
RESUME = "https://example.com/naveen-resume.pdf"  # conftest's resume_url

GOOD_JOB_FIELDS = {"company": "Microsoft", "role_title": "Product Manager II", "team": "Azure Core", "location": "Redmond, WA"}

GOOD_EMAIL = {
    "subject": "Product Manager II - Naveen Murali",
    "body": (
        "Hi Jane,\n\nYour Azure onboarding post made YAML sound almost fun, and it maps to the Product Manager II "
        "role on your team.\n\nAt Bizom I owned an AI-enabled ERP platform across 15+ clients and shipped an "
        "image-recognition module that lifted conversion by 25%.\n\nWould you have 15 minutes to talk about what "
        f"the team needs? My resume: {RESUME}\n\nBest,\nNaveen"
    ),
    "connection_note": "Hi Jane, I'm applying for the Product Manager II role on your team and loved your Azure onboarding post. I'd like to connect.",
}


def request_kind(kw: dict) -> str:
    props = kw["output_config"]["format"]["schema"]["properties"]
    if "company" in props:
        return "extract"
    if "connection_note" in props:
        return "email"
    return "legacy"


def job_responder(
    fields: dict | Callable[[dict], dict] | None = None,
    email: dict | Callable[[dict], dict] | None = None,
) -> Callable[[dict], dict]:
    """Answers Job extraction with `fields` and drafting with `email` (dicts or callables)."""

    def answer(kw: dict) -> dict:
        kind = request_kind(kw)
        if kind == "extract":
            f = fields if fields is not None else GOOD_JOB_FIELDS
            return f(kw) if callable(f) else dict(f)
        if kind == "email":
            e = email if email is not None else GOOD_EMAIL
            return e(kw) if callable(e) else dict(e)
        return dict(GOOD_PARTS)

    return answer
