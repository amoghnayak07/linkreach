"""Acceptance check: after a full run, logs hold no API key, cookie, email, or message body."""

from __future__ import annotations

import logging

from linkreach import logsetup, paths
from linkreach.commands import job, send
from linkreach.emailfinder import FinderResult

from tests.conftest import EXAMPLES, FAKE_KEY, base_session, freeze_weekday_morning, use_config
from tests.fakes import GOOD_EMAIL
from tests.helpers import add_approved, profile_for, url

FOUND_EMAIL = "jane.doe@contoso.com"


class Finder:
    def find(self, li, profile):
        return FinderResult(email=FOUND_EMAIL, source="test")


def all_logs() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths.logs_dir().glob("linkreach.log*"))


def test_full_run_logs_are_clean(env):
    use_config(env, {"pick_target": 1})  # connect_mode: automated, so the dormant send path runs too
    freeze_weekday_morning()
    paths.style_path().write_text((EXAMPLES / "style.example.md").read_text(encoding="utf-8"), encoding="utf-8")
    s = base_session()
    profile_for(s, "jane-doe", name="Jane Doe", headline="Engineering Manager, Azure Core", about="Hiring PMs for Azure AI.")
    jd = ["Product Manager II, Azure Core", "Microsoft is hiring a PM.", "END"]
    ctx = env.ctx(s, answers=jd + ["", "", "", ""] + [url("jane-doe"), "", ""], email_finder=Finder())

    assert job.run(ctx) == 0
    pick = env.db.picks(1)[0]
    assert pick["status"] == "drafted" and ctx.gmail.drafts[0][0] == FOUND_EMAIL

    pid = add_approved(env, "sam-lee", name="Sam Lee")
    page = profile_for(s, "sam-lee")
    assert send.run(env.ctx(s, answers=[""])) == 0
    row = env.db.get(pid)
    assert row["status"] == "sent" and page.send_clicks == 1

    # Try to leak secrets through the logger on purpose; redaction must catch them.
    log = logsetup.get("test")
    log.info(f"debug key={FAKE_KEY}")
    log.info("headers: Cookie: li_at=AQEDAXyz123; JSESSIONID=ajax:123")
    log.info("x", extra={"fields": {"note": row["note_sent"], "email_body": pick["email_body"], "cookie": "li_at=abc"}})
    for h in logging.getLogger("linkreach").handlers:
        h.flush()

    text = all_logs()
    assert text, "expected some log output"
    assert FAKE_KEY not in text and "sk-ant-api03" not in text
    assert "AQEDAXyz123" not in text and "li_at=abc" not in text and "ajax:123" not in text
    assert row["note_sent"] not in text
    assert FOUND_EMAIL not in text
    assert GOOD_EMAIL["subject"] not in text and GOOD_EMAIL["connection_note"] not in text
    assert "Azure onboarding post" not in text  # body text never logged
