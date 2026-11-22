"""Code-level checks on every draft before it is saved or sent.

A draft that fails any check is stored as `needs_detail` and can never be
approved until a new or edited version passes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_TLDS = (
    "com|net|org|io|ai|co|dev|app|xyz|info|biz|me|ly|gg|us|uk|in|ca|de|fr|example|link|site|"
    "online|tech|page|sh|so|to|tv|cc|ru|cn|top|click|live|store|shop|news|blog|edu|gov"
)
URL_RE = re.compile(
    r"(?:[a-z][a-z0-9+.\-]*://\S+)"           # any scheme
    r"|(?:\bwww\.\S+)"
    rf"|(?:\b[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:{_TLDS})\b(?:/\S*)?)",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\w)")
INSTRUCTION_RE = re.compile(
    r"\bignore\b|\bsystem\s+prompt\b|\bas\s+an\s+ai\b|\bprevious\s+instructions\b|\bdisregard\b"
    r"|\byou\s+are\s+now\b|\bnew\s+instructions\b|\bjailbreak\b|\blanguage\s+model\b"
    r"|^\s*assistant\s*:|</?\s*profile_data|<\s*/?\s*(?:script|system|instructions?)\b",
    re.I,
)
HTML_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.I)
INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u2060-\u2064\ufeff\u202a-\u202e\u2066-\u2069\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def only_length(self) -> bool:
        return bool(self.errors) and all(e.startswith("length:") for e in self.errors)

    def add(self, msg: str) -> None:
        if msg not in self.errors:
            self.errors.append(msg)


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _content_checks(label: str, text: str, resume_url: str, banned: list[str], res: Result, allow_resume: bool) -> None:
    scrubbed = text.replace(resume_url, " ") if (allow_resume and resume_url) else text
    for m in URL_RE.finditer(scrubbed):
        res.add(f"{label}: contains a URL other than resume_url ({m.group(0)[:60]})")
    if EMAIL_RE.search(scrubbed):
        res.add(f"{label}: contains an email address")
    if PHONE_RE.search(scrubbed):
        res.add(f"{label}: contains a phone number")
    m = INSTRUCTION_RE.search(text)
    if m:
        res.add(f"{label}: matches an instruction pattern ({m.group(0)!r})")
    if HTML_RE.search(text):
        res.add(f"{label}: contains HTML")
    if INVISIBLE_RE.search(text):
        res.add(f"{label}: contains control or zero-width characters")
    low = text.lower()
    for phrase in banned:
        if phrase.lower() in low:
            res.add(f"{label}: contains banned phrase {phrase!r}")


def validate_draft(
    note: str | None,
    followup: str | None,
    *,
    resume_url: str,
    banned_phrases: list[str],
    note_max_chars: int = 280,
    followup_max_words: int = 150,
) -> Result:
    res = Result()
    note = note or ""
    followup = followup or ""
    if not note.strip():
        res.add("note: empty")
    if not followup.strip():
        res.add("followup: empty")
    _content_checks("note", note, resume_url, banned_phrases, res, allow_resume=False)
    _content_checks("followup", followup, resume_url, banned_phrases, res, allow_resume=True)
    if len(note) > note_max_chars:
        res.add(f"length: note is {len(note)} characters (max {note_max_chars})")
    wc = word_count(followup)
    if wc > followup_max_words:
        res.add(f"length: follow-up is {wc} words (max {followup_max_words})")
    return res


def check(cfg, note: str | None, followup: str | None) -> Result:
    """validate_draft with the limits and phrases from a Config."""
    return validate_draft(
        note,
        followup,
        resume_url=cfg.resume_url,
        banned_phrases=cfg.banned_phrases,
        note_max_chars=cfg.note_max_chars,
        followup_max_words=cfg.followup_max_words,
    )


SUBJECT_MAX_CHARS = 80
BODY_MAX_WORDS = 200


def validate_email_draft(
    subject: str | None,
    body: str | None,
    note: str | None,
    *,
    resume_url: str,
    banned_phrases: list[str],
    note_max_chars: int = 200,
) -> Result:
    """Checks for a Job flow draft: email subject, email body, and Connection note.
    Only resume_url may appear as a link, and only in the body."""
    res = Result()
    subject, body, note = subject or "", body or "", note or ""
    for label, text in (("subject", subject), ("body", body), ("note", note)):
        if not text.strip():
            res.add(f"{label}: empty")
    if "\n" in subject.strip():
        res.add("subject: must be one line")
    _content_checks("subject", subject, resume_url, banned_phrases, res, allow_resume=False)
    _content_checks("body", body, resume_url, banned_phrases, res, allow_resume=True)
    _content_checks("note", note, resume_url, banned_phrases, res, allow_resume=False)
    if body.strip() and resume_url not in body:
        res.add("body: must include the resume link")
    if len(subject) > SUBJECT_MAX_CHARS:
        res.add(f"length: subject is {len(subject)} characters (max {SUBJECT_MAX_CHARS})")
    wc = word_count(body)
    if wc > BODY_MAX_WORDS:
        res.add(f"length: body is {wc} words (max {BODY_MAX_WORDS})")
    if len(note) > note_max_chars:
        res.add(f"length: note is {len(note)} characters (max {note_max_chars})")
    return res


def suspicious_context(text: str) -> list[str]:
    """Reasons a scraped context field should be kept out of the prompt entirely."""
    reasons = []
    if INSTRUCTION_RE.search(text):
        reasons.append("instruction pattern")
    if URL_RE.search(text):
        reasons.append("url")
    if EMAIL_RE.search(text):
        reasons.append("email")
    return reasons
