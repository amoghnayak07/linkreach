from __future__ import annotations

from datetime import timedelta

import pytest

from linkreach import clock
from linkreach.db import TransitionError, normalize_profile_url

from tests.helpers import add_drafted, url


def test_profile_url_normalized():
    a = normalize_profile_url("https://www.linkedin.com/in/Jane-Doe?miniProfileUrn=abc")
    b = normalize_profile_url("https://linkedin.com/in/jane-doe")
    c = normalize_profile_url("/in/jane-doe/details/experience/")
    assert a == b == c == "https://www.linkedin.com/in/jane-doe/"


def test_duplicate_url_adds_no_row(env):
    first = env.db.add_person(name="Jane", company="Microsoft", profile_url=url("jane-doe"))
    again = env.db.add_person(name="Jane D", company="Microsoft", profile_url="https://linkedin.com/in/JANE-DOE?x=1")
    assert first is not None and again is None
    assert len(env.db.people()) == 1


def test_auto_transitions_enforced(env):
    pid = env.db.add_person(name="A", company="Microsoft", profile_url=url("a"))
    with pytest.raises(TransitionError):
        env.db.set_status(pid, "sent")  # collected -> sent is not a valid step
    with pytest.raises(TransitionError):
        env.db.set_status(pid, "approved")  # must be drafted first
    env.db.set_status(pid, "needs_detail")
    with pytest.raises(TransitionError):
        env.db.set_status(pid, "approved")  # rejected drafts can't reach approved


def test_manual_cannot_approve(env):
    pid = add_drafted(env, "b")
    with pytest.raises(TransitionError):
        env.db.set_status(pid, "approved", source="dashboard", manual=True)
    env.db.set_status(pid, "dead", source="dashboard", manual=True)  # anything else is allowed by hand
    assert env.db.get(pid)["status"] == "dead"


def test_accepted_sets_follow_up_date_and_history(env):
    pid = add_drafted(env, "c")
    env.db.set_status(pid, "approved")
    env.db.set_status(pid, "sent")
    env.db.set_status(pid, "accepted", source="sync", follow_up_days=5)
    row = env.db.get(pid)
    expected = (clock.now().astimezone() + timedelta(days=5)).date().isoformat()
    assert row["follow_up_date"] == expected
    assert row["accepted_at"] and row["sent_at"]
    hist = [(h["old_status"], h["new_status"], h["source"]) for h in env.db.history(pid)]
    assert hist[-1] == ("sent", "accepted", "sync")
    assert [h[1] for h in hist] == ["collected", "drafted", "approved", "sent", "accepted"]


def test_mark_command(env, capsys):
    from linkreach.commands import misc

    pid = add_drafted(env, "d")
    assert misc.mark(env.ctx(), pid, "replied") == 0
    assert env.db.get(pid)["status"] == "replied"
    assert env.db.history(pid)[-1]["source"] == "cli"


def test_purge_removes_old_dead_and_skipped(env):
    old = add_drafted(env, "old")
    env.db.set_status(old, "dead")
    keep = add_drafted(env, "keep")
    env.db.set_status(keep, "skipped")
    env.db.log("send", "info", old, "x")
    env.db.conn.execute("UPDATE people SET updated_at = ? WHERE id = ?", (clock.days_ago_iso(200), old))
    env.db.conn.commit()
    assert env.db.purge(180) == 1
    assert env.db.get(old) is None and env.db.get(keep) is not None
    assert env.db.conn.execute("SELECT COUNT(*) FROM activity_log WHERE person_id = ?", (old,)).fetchone()[0] == 0
