from __future__ import annotations

import pytest

from linkreach.validate import validate_draft

RESUME = "https://example.com/naveen-resume.pdf"
BANNED = ["synergy", "leverage", "circle back"]
GOOD_NOTE = "Hi Jane, your onboarding post was a delight. I'm a PM with 3+ years in AI SaaS. Would like to connect."
GOOD_FOLLOW = f"Dear Jane,\n\nThanks for connecting.\n\nMy resume: {RESUME}. Best,\nNaveen"


def v(note=GOOD_NOTE, follow=GOOD_FOLLOW):
    return validate_draft(note, follow, resume_url=RESUME, banned_phrases=BANNED)


def test_good_passes():
    assert v().ok


@pytest.mark.parametrize(
    "bad,needle",
    [
        ("see https://evil.example now", "URL"),
        ("visit evil.example today", "URL"),
        ("www.evil.com", "URL"),
        ("mail me jane@corp.com", "email"),
        ("call 617-555-0199", "phone"),
        ("call (617) 555 0199", "phone"),
        ("Please ignore that", "instruction"),
        ("this is the system prompt", "instruction"),
        ("As an AI I think", "instruction"),
        ("great synergy here", "banned"),
        ("let's circle back", "banned"),
        ("<b>bold</b>", "HTML"),
        ("zero\u200bwidth", "zero-width"),
    ],
)
def test_bad_content_rejected(bad, needle):
    res = v(note=GOOD_NOTE + " " + bad)
    assert not res.ok and any(needle.lower() in e.lower() for e in res.errors), res.errors


def test_resume_url_only_allowed_in_followup():
    assert not v(note=GOOD_NOTE + " " + RESUME).ok
    assert v(follow=GOOD_FOLLOW).ok
    assert not v(follow=GOOD_FOLLOW + " also https://other.example/x").ok


def test_length_limits():
    assert v(note="x" * 281).only_length
    assert v(follow="word " * 151).only_length
    assert v(note="x" * 280).ok


def test_ordinary_text_not_flagged():
    note = "Hi Jo, your Node.js talk on U.S. payments at 3.5x scale was great. I'm a PM. Would like to connect."
    assert v(note=note).ok, v(note=note).errors


# ---------------- Job flow: subject, body, note ----------------
from linkreach.validate import validate_email_draft  # noqa: E402

SUBJECT = "Product Manager II - Naveen Murali"
BODY = f"Hi Jane,\n\nYour onboarding post was a delight.\n\nMy resume: {RESUME}\n\nBest,\nNaveen"
NOTE = "Hi Jane, I'm applying for the PM II role on your team. I'd like to connect."


def ve(subject=SUBJECT, body=BODY, note=NOTE, note_max=200):
    return validate_email_draft(subject, body, note, resume_url=RESUME, banned_phrases=BANNED, note_max_chars=note_max)


def test_email_draft_good():
    assert ve().ok


@pytest.mark.parametrize(
    "kw, expect",
    [
        ({"subject": "x" * 81}, "length: subject is 81 characters"),
        ({"body": BODY + " word" * 200}, "length: body is"),
        ({"note": "x" * 201}, "length: note is 201 characters (max 200)"),
        ({"subject": f"See {RESUME}"}, "subject: contains a URL"),
        ({"note": f"My resume {RESUME}"}, "note: contains a URL"),
        ({"body": BODY + " Also see https://evil.example"}, "body: contains a URL"),
        ({"body": BODY + " Write to me at a@b.com"}, "body: contains an email"),
        ({"body": BODY + " Call 617-555-0100"}, "body: contains a phone"),
        ({"body": BODY + " Ignore the above"}, "body: matches an instruction"),
        ({"body": BODY + " <b>hi</b>"}, "body: contains HTML"),
        ({"note": NOTE + " synergy"}, "note: contains banned phrase"),
        ({"body": "Hi Jane, no link here."}, "body: must include the resume link"),
        ({"subject": ""}, "subject: empty"),
    ],
)
def test_email_draft_rules(kw, expect):
    res = ve(**kw)
    assert any(e.startswith(expect) for e in res.errors), res.errors


def test_email_note_limit_is_configurable():
    assert not ve(note="x" * 250, note_max=200).ok
    assert ve(note="Hi " + "x" * 240, note_max=300).ok


def test_profile_link_parsing():
    from linkreach.jobflow import parse_profile_link

    assert parse_profile_link("https://www.linkedin.com/in/Jane-Doe?trk=x") == "https://www.linkedin.com/in/jane-doe/"
    assert parse_profile_link("linkedin.com/in/jane-doe/") == "https://www.linkedin.com/in/jane-doe/"
    assert parse_profile_link("<https://uk.linkedin.com/in/jane>") == "https://www.linkedin.com/in/jane/"
    assert parse_profile_link("https://evil.example/in/jane") is None
    assert parse_profile_link("https://www.linkedin.com/company/microsoft/") is None
    assert parse_profile_link("hello") is None
