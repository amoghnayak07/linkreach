"""Acceptance check: after a full run, logs hold no API key, cookie, or message body."""

from __future__ import annotations

import logging

from linkreach import logsetup, paths
from linkreach.commands import collect, review, send
from linkreach.drafting import Drafter, run_draft

from tests.conftest import FAKE_KEY, base_session, freeze_weekday_morning, use_config
from tests.fakes import FakeClaude, search_page
from tests.helpers import profile_for, url


def all_logs() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths.logs_dir().glob("linkreach.log*"))


def test_full_run_logs_are_clean(env):
    use_config(env)  # connect_mode: automated, so the run reaches send
    freeze_weekday_morning()
    s = base_session()
    s.default = search_page("x", [])
    s.add(search_page("microsoft", [("Jane Doe", "Technical Recruiter", url("jane-doe"))]))
    page = profile_for(s, "jane-doe", name="Jane Doe", headline="Recruiter", about="Hiring PMs for Azure AI.")
    ctx = env.ctx(s, answers=["a", ""], drafter=Drafter(env.inputs.config, client=FakeClaude()))

    assert collect.run(ctx) == 0
    run_draft(env.inputs, env.db, ctx.drafter)
    review.run(ctx, editor=lambda t: t)
    assert send.run(ctx) == 0
    row = env.db.get(1)
    assert row["status"] == "sent" and page.send_clicks == 1

    # Try to leak secrets through the logger on purpose; redaction must catch them.
    log = logsetup.get("test")
    log.info(f"debug key={FAKE_KEY}")
    log.info("headers: Cookie: li_at=AQEDAXyz123; JSESSIONID=ajax:123")
    log.info("x", extra={"fields": {"note": row["note_sent"], "followup_draft": row["followup_draft"], "cookie": "li_at=abc"}})
    for h in logging.getLogger("linkreach").handlers:
        h.flush()

    text = all_logs()
    assert text, "expected some log output"
    assert FAKE_KEY not in text and "sk-ant-api03" not in text
    assert "AQEDAXyz123" not in text and "li_at=abc" not in text and "ajax:123" not in text
    assert row["note_sent"] not in text
    assert row["followup_draft"][:60] not in text
    assert "Azure onboarding post" not in text  # opener text never logged
