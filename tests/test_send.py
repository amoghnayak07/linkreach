from __future__ import annotations

import pytest

from linkreach.commands import send
from linkreach.commands.common import EXIT_DOCTOR, EXIT_REFUSED
from linkreach.safety import CapReached, brake_status, check_request_caps

from tests.conftest import base_session, freeze_weekday_morning, use_config
from tests.helpers import add_approved, add_old_sent, profile_for, send_events


@pytest.fixture(autouse=True)
def _clock(env):
    use_config(env)  # connect_mode: automated; the send path is off by default
    freeze_weekday_morning()  # after env, which resets the clock


def test_manual_send_waits_for_enter_and_sends(env):
    pid = add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s, answers=[""])) == 0
    row = env.db.get(pid)
    assert row["status"] == "sent" and row["note_sent"] == row["note_draft"]
    assert page.typed == row["note_draft"]
    assert page.send_clicks == 1


def test_manual_skip(env):
    pid = add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s, answers=["s"])) == 0
    assert env.db.get(pid)["status"] == "skipped"
    assert page.send_clicks == 0


def test_unapproved_drafts_never_sent(env):
    from tests.helpers import add_drafted

    add_drafted(env, "draft-only")
    s = base_session()
    page = profile_for(s, "draft-only")
    assert send.run(env.ctx(s), auto=True) == 0
    assert page.send_clicks == 0 and s.visits == []


def test_daily_cap_blocks_even_with_auto(env):
    send_events(env.db, 20)
    add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    with pytest.raises(CapReached):
        check_request_caps(env.db, env.inputs.config)
    assert send.run(env.ctx(s), auto=True) == 0
    assert page.send_clicks == 0 and s.visits == []


def test_weekly_cap_blocks_even_with_auto(env):
    for d in range(1, 5):
        send_events(env.db, 20, days_ago=d)  # 80 in the last 7 days, none today
    add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True) == 0
    assert page.send_clicks == 0


def test_cap_reached_mid_run(env):
    send_events(env.db, 18)
    pages = []
    s = base_session()
    for i in range(5):
        add_approved(env, f"p{i}")
        pages.append(profile_for(s, f"p{i}"))
    assert send.run(env.ctx(s), auto=True) == 0
    assert sum(p.send_clicks for p in pages) == 2
    assert env.db.count_events("send", "0000") == 20


def test_brake_trips_and_blocks_auto(env, capsys):
    add_old_sent(env, 30, accepted=5)  # 17% < 25%
    b = brake_status(env.db, env.inputs.config)
    assert b.sample == 30 and b.tripped
    add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    ctx = env.ctx(s)
    assert send.run(ctx, auto=True) == EXIT_REFUSED
    assert ctx.factory_calls["n"] == 0 and page.send_clicks == 0
    assert "brake" in capsys.readouterr().out.lower()


def test_override_brake_allows_auto(env):
    add_old_sent(env, 30, accepted=5)
    pid = add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True, override_brake=True) == 0
    assert page.send_clicks == 1 and env.db.get(pid)["status"] == "sent"


def test_brake_needs_30_old_requests(env):
    add_old_sent(env, 29, accepted=0)
    assert not brake_status(env.db, env.inputs.config).tripped
    add_old_sent(env, 10, accepted=0, days_ago=2)  # too recent to count
    assert brake_status(env.db, env.inputs.config).sample == 29


def test_brake_ok_at_25_percent(env):
    add_old_sent(env, 40, accepted=10)
    assert not brake_status(env.db, env.inputs.config).tripped


def test_auto_aborts_when_doctor_fails(env):
    add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    ctx = env.ctx(s, api_check=lambda m: (False, "API key rejected (401)"))
    assert send.run(ctx, auto=True) == EXIT_DOCTOR
    assert page.send_clicks == 0
    assert any(r["command"] == "doctor" and r["event"] == "fail" for r in env.db.activity())


def test_auto_aborts_when_doctor_selectors_fail(env):
    add_approved(env, "jane")
    s = base_session()
    s.pages["https://www.linkedin.com/in/doctor-test/"].broken = True
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True) == EXIT_DOCTOR
    assert page.send_clicks == 0


def test_auto_outside_window_refuses(env):
    use_config(env, {"auto_window": {"days": ["sat"], "start": "09:00", "end": "18:00"}})
    add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True) == EXIT_REFUSED
    assert page.send_clicks == 0


def test_kill_after_click_then_restart_sends_no_duplicate(env):
    pid = add_approved(env, "jane")
    s = base_session()

    def die():
        raise KeyboardInterrupt  # process killed right after LinkedIn registered the click

    page = profile_for(s, "jane", send_effect=die)
    assert send.run(env.ctx(s), auto=True) == 130
    row = env.db.get(pid)
    assert row["status"] == "approved" and row["send_attempted_at"]
    assert page.send_clicks == 1

    page.send_effect = None  # restart
    assert send.run(env.ctx(s), auto=True) == 0
    row = env.db.get(pid)
    assert row["status"] == "sent"
    assert page.send_clicks == 1  # no second click
    assert env.db.count_events("send", "0000") == 1


def test_kill_before_click_then_restart_marks_failed_not_resent(env):
    pid = add_approved(env, "jane")
    env.db.update_fields(pid, send_attempted_at="2026-11-18T14:00:00+00:00")  # marker committed, click never happened
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True) == 0
    assert env.db.get(pid)["status"] == "failed"
    assert page.send_clicks == 0


def test_pending_not_shown_marks_failed_and_moves_on(env):
    a = add_approved(env, "a")
    b = add_approved(env, "b")
    s = base_session()
    profile_for(s, "a", pending_after_send=False)
    pb = profile_for(s, "b")
    assert send.run(env.ctx(s), auto=True) == 0
    assert env.db.get(a)["status"] == "failed"
    assert env.db.get(b)["status"] == "sent" and pb.send_clicks == 1


def test_already_connected_not_sent(env):
    pid = add_approved(env, "friend")
    s = base_session()
    page = profile_for(s, "friend", first_degree=True)
    assert send.run(env.ctx(s), auto=True) == 0
    assert env.db.get(pid)["status"] == "accepted" and page.send_clicks == 0


def test_alumni_first_then_oldest(env):
    sf = add_approved(env, "sf", company="Salesforce")
    ms = add_approved(env, "ms", company="Microsoft")
    al = add_approved(env, "al", company="Salesforce", alumni=1)
    order = [r["id"] for r in send.candidates(env.ctx())]
    assert order == [al, sf, ms]


def test_note_that_no_longer_validates_is_not_sent(env):
    pid = add_approved(env, "jane")
    env.db.update_fields(pid, note_draft="Hi Jane, see https://evil.example for more.")
    s = base_session()
    page = profile_for(s, "jane")
    assert send.run(env.ctx(s), auto=True) == 0
    row = env.db.get(pid)
    assert row["status"] == "needs_detail" and "URL" in row["validation_errors"]
    assert page.send_clicks == 0


def test_sync_marks_accepted(env):
    from linkreach.commands import sync

    pid = add_approved(env, "jane")
    env.db.set_status(pid, "sent")
    s = base_session()
    profile_for(s, "jane", first_degree=True)
    assert sync.run(env.ctx(s)) == 0
    row = env.db.get(pid)
    assert row["status"] == "accepted" and row["follow_up_date"] == "2026-11-23"
    assert env.db.history(pid)[-1]["source"] == "sync"
