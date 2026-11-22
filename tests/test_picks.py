"""Pick lifecycle (ticket 04): `mark`, `list`, and the already-emailed flag."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from linkreach import clock
from linkreach.cli import main
from linkreach.commands import job, misc
from linkreach.commands.common import EXIT_OK
from linkreach.db import PICK_MANUAL_TRANSITIONS, PICK_STATUSES, TransitionError

from tests.helpers import url
from tests.test_job import answers, session_with, supplied_only, write_style  # noqa: F401  (autouse fixture)


def make_pick(env, slug: str = "jane-doe", status: str = "no_email", company: str = "Microsoft", role: str = "PM", job_id: int | None = None) -> int:
    """A Pick already moved to `status` (via valid steps), on a new Job unless job_id is given."""
    if job_id is None:
        job_id = env.db.add_job(company=company, description="jd", role_title=role)
    pid = env.db.ensure_person(url(slug), name=slug.replace("-", " ").title(), company=company)
    pick_id = env.db.add_pick(job_id, pid, "supplied")
    assert pick_id is not None
    path = {
        "picked": [],
        "no_email": ["no_email"],
        "drafted": ["drafted"],
        "needs_detail": ["needs_detail"],
        "emailed": ["no_email", "emailed"],
        "connected": ["no_email", "connected"],
        "replied": ["no_email", "emailed", "replied"],
        "meeting": ["no_email", "emailed", "replied", "meeting"],
        "referral": ["no_email", "emailed", "replied", "meeting", "referral"],
        "dead": ["dead"],
    }[status]
    for st in path:
        env.db.set_pick_status(pick_id, st, manual=st not in ("drafted", "no_email", "needs_detail"))
    return pick_id


def status_of(env, pick_id: int) -> str:
    return env.db.get_pick(pick_id)["status"]


# ---------------------------------------------------------------- transitions


@pytest.mark.parametrize(
    "start,target",
    [
        ("drafted", "emailed"),
        ("drafted", "connected"),
        ("no_email", "emailed"),
        ("no_email", "connected"),
        ("emailed", "connected"),
        ("connected", "emailed"),
        ("emailed", "replied"),
        ("connected", "replied"),
        ("replied", "meeting"),
        ("meeting", "referral"),
    ]
    + [(s, "dead") for s in PICK_STATUSES if s != "dead"],
)
def test_valid_manual_moves(env, start, target):
    p = make_pick(env, status=start)
    assert misc.mark_pick(env.ctx(), p, target) == 0
    assert status_of(env, p) == target
    last = env.db.pick_history(p)[-1]
    assert (last["old_status"], last["new_status"], last["source"]) == (start, target, "cli")


@pytest.mark.parametrize(
    "start,target",
    [
        ("picked", "emailed"),  # nothing drafted yet
        ("needs_detail", "connected"),
        ("drafted", "replied"),  # replied comes after emailed or connected
        ("no_email", "meeting"),
        ("emailed", "meeting"),  # skips replied
        ("replied", "referral"),  # skips meeting
        ("referral", "emailed"),  # no going back
        ("meeting", "replied"),
        ("dead", "emailed"),  # dead is final
    ],
)
def test_invalid_manual_moves_are_rejected(env, capsys, start, target):
    p = make_pick(env, status=start)
    before = len(env.db.pick_history(p))
    assert misc.mark_pick(env.ctx(), p, target) == 1
    assert status_of(env, p) == start
    assert len(env.db.pick_history(p)) == before
    out = capsys.readouterr().out
    assert f"cannot move a pick from {start} to {target}" in out


def test_rejection_says_where_the_pick_can_go(env, capsys):
    p = make_pick(env, status="emailed")
    misc.mark_pick(env.ctx(), p, "referral")
    assert "it can go to: connected, replied, dead" in capsys.readouterr().out


@pytest.mark.parametrize("target", ["picked", "drafted", "no_email", "needs_detail"])
def test_statuses_linkreach_sets_cannot_be_set_by_hand(env, capsys, target):
    p = make_pick(env, status="emailed")
    assert misc.mark_pick(env.ctx(), p, target) == 1
    assert status_of(env, p) == "emailed"
    assert "set by linkreach itself" in capsys.readouterr().out
    with pytest.raises(TransitionError):
        env.db.set_pick_status(p, target, manual=True)


def test_hand_set_guard_applies_even_where_linkreach_could_move(env):
    p = make_pick(env, status="picked")  # linkreach may move picked -> drafted; the user may not
    with pytest.raises(TransitionError, match="set by linkreach itself"):
        env.db.set_pick_status(p, "drafted", manual=True)
    env.db.set_pick_status(p, "drafted")  # linkreach's own path still works
    assert status_of(env, p) == "drafted"


def test_linkreach_cannot_make_the_users_moves(env):
    p = make_pick(env, status="no_email")
    with pytest.raises(TransitionError):
        env.db.set_pick_status(p, "emailed")  # not manual


def test_every_manual_target_is_a_user_status():
    targets = set().union(*PICK_MANUAL_TRANSITIONS.values())
    assert targets == {"emailed", "connected", "replied", "meeting", "referral", "dead"}


def test_marking_the_same_status_is_a_no_op(env, capsys):
    p = make_pick(env, status="emailed")
    before = len(env.db.pick_history(p))
    assert misc.mark_pick(env.ctx(), p, "emailed") == 0
    assert len(env.db.pick_history(p)) == before
    assert "already" in capsys.readouterr().out


def test_unknown_pick_id(env, capsys):
    assert misc.mark_pick(env.ctx(), 999, "emailed") == 1
    assert "No Pick #999" in capsys.readouterr().out


def test_mark_through_the_cli(env, capsys):
    p = make_pick(env, status="no_email")
    assert main(["mark", str(p), "emailed"]) == 0
    assert status_of(env, p) == "emailed"
    assert main(["mark", str(p), "drafted"]) == 1
    assert "set by linkreach itself" in capsys.readouterr().out


def test_mark_and_list_through_the_cli(env):
    p = make_pick(env, status="drafted")
    assert main(["mark", str(p), "connected"]) == 0
    assert main(["list"]) == 0


def test_person_level_mark_is_untouched(env):
    from tests.helpers import add_drafted

    pid = add_drafted(env, "old-flow")
    assert misc.mark(env.ctx(), pid, "replied") == 0  # old person statuses still work for `send`
    assert env.db.get(pid)["status"] == "replied"


# ---------------------------------------------------------------- list


def test_list_filters_by_job_and_status(env, capsys):
    a = make_pick(env, "alice-a", status="no_email", company="Microsoft", role="PM")
    job_a = env.db.get_pick(a)["job_id"]
    b = make_pick(env, "bob-b", status="emailed", job_id=job_a)
    c = make_pick(env, "carol-c", status="no_email", company="Contoso", role="TPM")
    env.db.update_pick(b, email="bob@microsoft.com")

    def rows(job_id=None, status=None) -> str:
        capsys.readouterr()
        assert misc.list_picks(env.ctx(), job_id, status) == 0
        return capsys.readouterr().out

    out = rows()
    assert "Alice A" in out and "Bob B" in out and "Carol C" in out and "3 picks" in out
    assert "PM at Microsoft" in out and "TPM at Contoso" in out

    out = rows(job_id=job_a)
    assert "Alice A" in out and "Bob B" in out and "Carol C" not in out and "2 picks" in out

    out = rows(status="no_email")
    assert "Alice A" in out and "Carol C" in out and "Bob B" not in out

    out = rows(job_id=job_a, status="emailed")
    assert "Bob B" in out and "Alice A" not in out and "1 picks" in out
    assert "found" in out  # Bob's email was found
    assert "bob@microsoft.com" not in out  # whether, not what

    out = rows(status="referral")
    assert "0 picks" in out
    assert c  # silence unused


def test_list_unknown_job(env, capsys):
    assert misc.list_picks(env.ctx(), 42) == 1
    assert "No Job #42" in capsys.readouterr().out


def test_list_through_the_cli(env, capsys):
    make_pick(env, "dee-d", status="no_email")
    capsys.readouterr()
    assert main(["list", "--job", "1", "--status", "no_email"]) == 0
    assert "Dee D" in capsys.readouterr().out


# ---------------------------------------------------------------- already-emailed flag


def flag_run(env, capsys, slug: str = "jane-doe", confirm: list[str] | None = None) -> str:
    write_style()
    s = session_with(slug)
    capsys.readouterr()
    assert job.run(env.ctx(s, answers=answers([url(slug)], confirm=confirm))) == EXIT_OK
    out = capsys.readouterr().out
    return out.split("Picks (1)", 1)[1].split("Enter to start", 1)[0] if "Picks (1)" in out else out


def test_person_emailed_for_another_job_is_flagged_and_kept(env, capsys):
    clock.freeze(datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc))
    old = make_pick(env, "jane-doe", status="emailed", company="Contoso", role="Senior PM")
    clock.reset()
    old_job = env.db.get_pick(old)["job_id"]
    local_day = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc).astimezone().date().isoformat()

    shown = flag_run(env, capsys)
    assert f"already emailed on {local_day} for Job #{old_job} Senior PM at Contoso" in shown

    new_job = old_job + 1
    kept = env.db.picks(new_job)
    assert [r["profile_url"] for r in kept] == [url("jane-doe")]  # not blocked
    assert kept[0]["status"] == "no_email"
    assert kept[0]["person_id"] == env.db.get_pick(old)["person_id"]


def test_flag_survives_later_statuses(env, capsys):
    make_pick(env, "jane-doe", status="referral", company="Contoso")
    assert "already emailed on" in flag_run(env, capsys)


def test_flag_for_person_marked_dead_after_emailing(env, capsys):
    p = make_pick(env, "jane-doe", status="emailed", company="Contoso")
    env.db.set_pick_status(p, "dead", manual=True)
    assert "already emailed on" in flag_run(env, capsys)


def test_reached_replied_via_connected_is_flagged_as_contacted(env, capsys):
    p = make_pick(env, "jane-doe", status="connected", company="Contoso")
    env.db.set_pick_status(p, "replied", manual=True)
    shown = flag_run(env, capsys)
    assert "already contacted on" in shown and "(now replied)" in shown


@pytest.mark.parametrize("status", ["picked", "no_email", "drafted", "connected", "dead"])
def test_no_flag_when_never_emailed(env, capsys, status):
    make_pick(env, "jane-doe", status=status, company="Contoso")
    assert "already" not in flag_run(env, capsys)


def test_no_flag_for_a_new_person(env, capsys):
    make_pick(env, "someone-else", status="emailed")
    assert "already" not in flag_run(env, capsys)


def test_flagged_pick_can_still_be_removed(env, capsys):
    make_pick(env, "jane-doe", status="emailed", company="Contoso")
    write_style()
    s = session_with("jane-doe")
    # Remove the only link, then press Enter on the empty list: nothing saved, nothing read.
    assert job.run(env.ctx(s, answers=answers([url("jane-doe")], confirm=["-1", ""]))) == EXIT_OK
    assert env.db.get_job(2) is None
    assert url("jane-doe") not in s.visits


def test_prior_contacts_excludes_the_given_job(env):
    p = make_pick(env, "jane-doe", status="emailed")
    row = env.db.get_pick(p)
    assert len(env.db.prior_contacts(row["person_id"])) == 1
    assert env.db.prior_contacts(row["person_id"], exclude_job_id=row["job_id"]) == []
