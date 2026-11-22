from __future__ import annotations

from datetime import timedelta

from linkreach import clock
from linkreach.db import DB

from tests.fakes import ProfilePage

# A connection note on a Person, for the dormant send path (ADR-0001). Passes validation.
PERSON_NOTE = "Hi {first}, your Azure onboarding post made YAML sound almost fun. I ran AI rollouts across 15+ enterprise clients at Bizom. Would like to connect."


def url(slug: str) -> str:
    return f"https://www.linkedin.com/in/{slug}/"


def add_drafted(env, slug: str, name: str = "Jane Doe", company: str = "Microsoft", alumni: int = 0) -> int:
    db: DB = env.db
    pid = db.add_person(
        name=name, title="Technical Recruiter", company=company, profile_url=url(slug),
        is_alumni=alumni, context_1="Leads early-career hiring for Azure", context_2="Posted about onboarding",
    )
    assert pid is not None
    db.update_fields(pid, note_draft=PERSON_NOTE.format(first=name.split()[0]))
    db.set_status(pid, "drafted")
    return pid


def add_approved(env, slug: str, **kw) -> int:
    pid = add_drafted(env, slug, **kw)
    env.db.set_status(pid, "approved")
    return pid


def add_old_sent(env, n: int, accepted: int, days_ago: int = 10) -> None:
    """n requests sent `days_ago` days ago, `accepted` of them accepted."""
    when = clock.iso(clock.now() - timedelta(days=days_ago))
    for i in range(n):
        pid = add_approved(env, f"old-{days_ago}-{i}", name=f"Old Person{i}")
        env.db.set_status(pid, "sent", sent_at=when)
        if i < accepted:
            env.db.set_status(pid, "accepted")


def profile_for(session, slug: str, **kw) -> ProfilePage:
    kw.setdefault("name", slug.replace("-", " ").title())
    return session.add(ProfilePage(url(slug), **kw))


def send_events(db: DB, n: int, days_ago: float = 0) -> None:
    ts = clock.iso(clock.now() - timedelta(days=days_ago))
    for _ in range(n):
        db.conn.execute(
            "INSERT INTO activity_log (timestamp, command, event, person_id, detail) VALUES (?, 'send', 'send', NULL, 'seed')",
            (ts,),
        )
    db.conn.commit()
