"""SQLite storage, status transitions, and activity logging.

Every write commits immediately, so a crash or Ctrl-C loses one action at most.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from linkreach import clock, paths

STATUSES = [
    "collected",
    "needs_detail",
    "drafted",
    "approved",
    "skipped",
    "sent",
    "failed",
    "accepted",
    "followed_up",
    "replied",
    "meeting",
    "referral",
    "dead",
]

# Transitions the tool makes on its own (collect, draft, review, send, sync).
AUTO_TRANSITIONS: dict[str, set[str]] = {
    "collected": {"drafted", "needs_detail", "skipped", "dead"},
    "needs_detail": {"drafted", "needs_detail", "skipped", "dead"},
    "drafted": {"approved", "drafted", "needs_detail", "skipped", "dead"},
    "approved": {"sent", "failed", "skipped", "drafted", "needs_detail", "accepted"},
    "skipped": {"drafted", "needs_detail", "collected", "dead"},
    "sent": {"accepted", "failed", "dead"},
    "failed": {"approved", "drafted", "skipped", "dead"},
    "accepted": {"followed_up", "replied", "meeting", "referral", "dead"},
    "followed_up": {"replied", "meeting", "referral", "dead"},
    "replied": {"meeting", "referral", "dead"},
    "meeting": {"referral", "dead"},
    "referral": {"dead"},
    "dead": set(),
}

# Statuses a person may never be set to by hand (dashboard or `mark`).
# `approved` must go through `review`, which validates the draft first.
MANUAL_FORBIDDEN = {"approved"}

# Statuses that mean "a request went out".
SENT_OR_LATER = {"sent", "accepted", "followed_up", "replied", "meeting", "referral"}
ACCEPTED_OR_LATER = {"accepted", "followed_up", "replied", "meeting", "referral"}

EVENTS = {"view", "send", "fail", "stop", "captcha", "selector_broken", "run", "info"}

# Outreach progress per Pick (one Person for one Job). linkreach sets statuses up to
# drafted / no_email / needs_detail; the user sets the rest with `mark` (ticket 04).
PICK_STATUSES = [
    "picked", "drafted", "no_email", "needs_detail",
    "emailed", "connected", "replied", "meeting", "referral", "dead",
]
PICK_AUTO_TRANSITIONS: dict[str, set[str]] = {
    "picked": {"drafted", "no_email", "needs_detail", "dead"},
    "needs_detail": {"drafted", "no_email", "dead"},
}
PICK_ORIGINS = ("supplied", "found")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT NOT NULL,
    profile_url TEXT NOT NULL UNIQUE,
    bucket TEXT,
    is_alumni INTEGER NOT NULL DEFAULT 0,
    context_1 TEXT,
    context_2 TEXT,
    job_title TEXT,
    status TEXT NOT NULL DEFAULT 'collected',
    note_draft TEXT,
    note_sent TEXT,
    followup_draft TEXT,
    collected_at TEXT NOT NULL,
    sent_at TEXT,
    accepted_at TEXT,
    follow_up_date TEXT,
    followed_up_at TEXT,
    my_notes TEXT,
    -- additions beyond the spec's column list:
    user_detail TEXT,           -- one line of context you typed in `review`
    validation_errors TEXT,     -- why the last draft was rejected
    send_attempted_at TEXT,     -- written BEFORE clicking Send; prevents duplicate sends after a crash
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_people_status ON people(status);
CREATE INDEX IF NOT EXISTS idx_people_company ON people(company);

CREATE TABLE IF NOT EXISTS openers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    opener_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    old_status TEXT,
    new_status TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('cli', 'dashboard', 'sync')),
    pick_id INTEGER              -- set when the change is to a Pick, not the person-level status
);
CREATE INDEX IF NOT EXISTS idx_history_person ON status_history(person_id);

-- One role at one company, created from a pasted job description.
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    role_title TEXT,
    team TEXT,
    location TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- A Person chosen for a Job. Outreach progress lives here, not on the person.
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    person_id INTEGER NOT NULL REFERENCES people(id),
    origin TEXT NOT NULL CHECK (origin IN ('supplied', 'found')),
    tier TEXT,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'picked',
    email TEXT,
    email_subject TEXT,
    email_body TEXT,
    connection_note TEXT,
    validation_errors TEXT,
    user_detail TEXT,
    gmail_draft_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (job_id, person_id)
);
CREATE INDEX IF NOT EXISTS idx_picks_job ON picks(job_id);
CREATE INDEX IF NOT EXISTS idx_picks_person ON picks(person_id);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    command TEXT NOT NULL,
    event TEXT NOT NULL,
    person_id INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_activity_event ON activity_log(event, timestamp);

-- LinkedIn's numeric id per company slug, so collect doesn't spend a page view on it every run.
CREATE TABLE IF NOT EXISTS company_ids (
    slug TEXT PRIMARY KEY COLLATE NOCASE,
    company_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class TransitionError(ValueError):
    pass


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring databases created before Jobs and Picks up to date."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(status_history)")}
    if "pick_id" not in cols:
        conn.execute("ALTER TABLE status_history ADD COLUMN pick_id INTEGER")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_history_pick ON status_history(pick_id)")


def normalize_profile_url(url: str) -> str:
    """Canonical form used as the unique key: https://www.linkedin.com/in/<slug>/"""
    url = url.strip()
    if url.startswith("/"):
        url = "https://www.linkedin.com" + url
    parts = urlsplit(url)
    path = parts.path
    segs = [s for s in path.split("/") if s]
    if len(segs) >= 2 and segs[0] == "in":
        return f"https://www.linkedin.com/in/{segs[1].lower()}/"
    return f"https://www.linkedin.com{path.rstrip('/').lower()}/"


@dataclass
class DB:
    conn: sqlite3.Connection
    path: Path

    # ---------- lifecycle ----------
    @classmethod
    def open(cls, path: Path | None = None) -> "DB":
        path = path or paths.db_path()
        paths.secure_dir(path.parent)
        conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
        paths.secure_file(path)
        for suffix in ("-wal", "-shm"):
            paths.secure_file(Path(str(path) + suffix))
        return cls(conn=conn, path=path)

    def close(self) -> None:
        self.conn.close()

    def integrity_ok(self) -> bool:
        row = self.conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"

    # ---------- people ----------
    # ---------- company ids ----------
    COMPANY_ID_MAX_AGE_DAYS = 90

    def get_company_id(self, slug: str) -> str | None:
        """Cached LinkedIn company id, or None if unknown or older than 90 days."""
        row = self.conn.execute("SELECT company_id, updated_at FROM company_ids WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["updated_at"] < clock.days_ago_iso(self.COMPANY_ID_MAX_AGE_DAYS):
            return None
        return row["company_id"]

    def set_company_id(self, slug: str, company_id: str) -> None:
        if not (company_id or "").isdigit():
            raise ValueError("company id must be numeric")
        self.conn.execute(
            "INSERT INTO company_ids (slug, company_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(slug) DO UPDATE SET company_id = excluded.company_id, updated_at = excluded.updated_at",
            (slug, company_id, clock.now_iso()),
        )
        self.conn.commit()

    def forget_company_id(self, slug: str) -> None:
        self.conn.execute("DELETE FROM company_ids WHERE slug = ?", (slug,))
        self.conn.commit()

    def has_profile(self, profile_url: str) -> bool:
        url = normalize_profile_url(profile_url)
        return self.conn.execute("SELECT 1 FROM people WHERE profile_url = ?", (url,)).fetchone() is not None

    def add_person(self, **fields: Any) -> int | None:
        """Insert a collected person. Returns the new id, or None if the URL is already known."""
        fields = dict(fields)
        fields["profile_url"] = normalize_profile_url(fields["profile_url"])
        fields.setdefault("status", "collected")
        fields.setdefault("collected_at", clock.now_iso())
        fields["updated_at"] = fields["collected_at"]
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO people ({cols}) VALUES ({marks})",  # nosec B608 - column names are code constants
            tuple(fields.values()),
        )
        self.conn.commit()
        if cur.rowcount == 0:
            return None
        pid = int(cur.lastrowid or 0)
        self._history(pid, None, fields["status"], "cli")
        self.conn.commit()
        return pid

    def get(self, person_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()

    def people(self, statuses: Iterable[str] | None = None) -> list[sqlite3.Row]:
        if statuses is None:
            return list(self.conn.execute("SELECT * FROM people ORDER BY id"))
        statuses = list(statuses)
        marks = ", ".join("?" for _ in statuses)
        return list(
            self.conn.execute(
                f"SELECT * FROM people WHERE status IN ({marks}) ORDER BY id",  # nosec B608 - placeholders only
                statuses,
            )
        )

    def update_fields(self, person_id: int, **fields: Any) -> None:
        allowed = {
            "name", "title", "bucket", "is_alumni", "context_1", "context_2", "job_title",
            "note_draft", "note_sent", "followup_draft", "sent_at", "accepted_at",
            "follow_up_date", "followed_up_at", "my_notes", "user_detail",
            "validation_errors", "send_attempted_at",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown field(s): {bad}")
        if not fields:
            return
        fields["updated_at"] = clock.now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE people SET {sets} WHERE id = ?",  # nosec B608 - keys checked against allowlist
            (*fields.values(), person_id),
        )
        self.conn.commit()

    def set_status(
        self,
        person_id: int,
        new_status: str,
        source: str = "cli",
        manual: bool = False,
        follow_up_days: int = 5,
        **fields: Any,
    ) -> None:
        """Change status, apply side-effect timestamps, write status_history, commit."""
        if new_status not in STATUSES:
            raise TransitionError(f"unknown status {new_status!r}")
        row = self.get(person_id)
        if row is None:
            raise TransitionError(f"no person with id {person_id}")
        old = row["status"]
        if manual:
            if new_status in MANUAL_FORBIDDEN:
                raise TransitionError("approve drafts in `linkreach review`, which validates them first")
        elif new_status != old and new_status not in AUTO_TRANSITIONS.get(old, set()):
            raise TransitionError(f"cannot move from {old} to {new_status}")
        if new_status == old and not fields:
            return

        now = clock.now()
        updates: dict[str, Any] = dict(fields)
        if new_status == "sent" and not row["sent_at"] and "sent_at" not in updates:
            updates["sent_at"] = clock.iso(now)
        if new_status in ACCEPTED_OR_LATER and not row["accepted_at"] and "accepted_at" not in updates:
            if new_status == "accepted":
                updates["accepted_at"] = clock.iso(now)
        if new_status == "accepted" and not row["follow_up_date"] and "follow_up_date" not in updates:
            updates["follow_up_date"] = (now.astimezone() + timedelta(days=follow_up_days)).date().isoformat()
        if new_status == "followed_up" and "followed_up_at" not in updates:
            updates["followed_up_at"] = clock.iso(now)
        if new_status == "approved" and "send_attempted_at" not in updates:
            updates["send_attempted_at"] = None

        updates["status"] = new_status
        updates["updated_at"] = clock.iso(now)
        sets = ", ".join(f"{k} = ?" for k in updates)
        self.conn.execute(
            f"UPDATE people SET {sets} WHERE id = ?",  # nosec B608 - keys are code constants
            (*updates.values(), person_id),
        )
        if new_status != old:
            self._history(person_id, old, new_status, source)
        self.conn.commit()

    def _history(self, person_id: int, old: str | None, new: str, source: str, pick_id: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO status_history (person_id, old_status, new_status, changed_at, source, pick_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (person_id, old, new, clock.now_iso(), source, pick_id),
        )

    def history(self, person_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM status_history WHERE person_id = ? ORDER BY id", (person_id,)
            )
        )

    # ---------- jobs ----------
    def add_job(self, company: str, description: str, role_title: str = "", team: str = "", location: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO jobs (company, role_title, team, location, description, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (company, role_title or None, team or None, location or None, description, clock.now_iso()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    # ---------- picks ----------
    def ensure_person(self, profile_url: str, name: str, company: str) -> int:
        """Id of the Person with this profile, creating them if new. A known Person is reused
        as is, so their history across Jobs stays in one place."""
        url = normalize_profile_url(profile_url)
        row = self.conn.execute("SELECT id FROM people WHERE profile_url = ?", (url,)).fetchone()
        if row is not None:
            return int(row["id"])
        pid = self.add_person(name=name, company=company, profile_url=url)
        assert pid is not None
        return pid

    def add_pick(self, job_id: int, person_id: int, origin: str, tier: str | None = None, reason: str | None = None) -> int | None:
        """New Pick in status `picked`. Returns None if this Person is already a Pick for this Job."""
        if origin not in PICK_ORIGINS:
            raise ValueError(f"unknown pick origin {origin!r}")
        now = clock.now_iso()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO picks (job_id, person_id, origin, tier, reason, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'picked', ?, ?)",
            (job_id, person_id, origin, tier, reason, now, now),
        )
        if cur.rowcount == 0:
            self.conn.commit()
            return None
        pick_id = int(cur.lastrowid or 0)
        self._history(person_id, None, "picked", "cli", pick_id=pick_id)
        self.conn.commit()
        return pick_id

    def get_pick(self, pick_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT picks.*, people.name, people.title, people.company, people.profile_url, people.is_alumni, "
            "people.context_1, people.context_2 FROM picks JOIN people ON people.id = picks.person_id WHERE picks.id = ?",
            (pick_id,),
        ).fetchone()

    def picks(self, job_id: int, statuses: Iterable[str] | None = None) -> list[sqlite3.Row]:
        sql = (
            "SELECT picks.*, people.name, people.title, people.company, people.profile_url, people.is_alumni, "
            "people.context_1, people.context_2 FROM picks JOIN people ON people.id = picks.person_id "
            "WHERE picks.job_id = ?"
        )
        args: list[Any] = [job_id]
        if statuses is not None:
            statuses = list(statuses)
            sql += f" AND picks.status IN ({', '.join('?' for _ in statuses)})"
            args += statuses
        return list(self.conn.execute(sql + " ORDER BY picks.id", args))  # nosec B608 - placeholders only

    def update_pick(self, pick_id: int, **fields: Any) -> None:
        allowed = {
            "tier", "reason", "email", "email_subject", "email_body", "connection_note",
            "validation_errors", "user_detail", "gmail_draft_id",
        }
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown field(s): {bad}")
        if not fields:
            return
        fields["updated_at"] = clock.now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE picks SET {sets} WHERE id = ?",  # nosec B608 - keys checked against allowlist
            (*fields.values(), pick_id),
        )
        self.conn.commit()

    def set_pick_status(self, pick_id: int, new_status: str, source: str = "cli", **fields: Any) -> None:
        """Move a Pick along the automatic part of its lifecycle, writing status_history."""
        if new_status not in PICK_STATUSES:
            raise TransitionError(f"unknown pick status {new_status!r}")
        row = self.conn.execute("SELECT status, person_id FROM picks WHERE id = ?", (pick_id,)).fetchone()
        if row is None:
            raise TransitionError(f"no pick with id {pick_id}")
        old = row["status"]
        if new_status != old and new_status not in PICK_AUTO_TRANSITIONS.get(old, set()):
            raise TransitionError(f"cannot move a pick from {old} to {new_status}")
        if fields:
            self.update_pick(pick_id, **fields)
        if new_status == old:
            return
        self.conn.execute(
            "UPDATE picks SET status = ?, updated_at = ? WHERE id = ?", (new_status, clock.now_iso(), pick_id)
        )
        self._history(int(row["person_id"]), old, new_status, source, pick_id=pick_id)
        self.conn.commit()

    def pick_history(self, pick_id: int) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM status_history WHERE pick_id = ? ORDER BY id", (pick_id,)))

    # ---------- openers ----------
    def add_opener(self, person_id: int, text: str) -> None:
        self.conn.execute(
            "INSERT INTO openers (person_id, opener_text, created_at) VALUES (?, ?, ?)",
            (person_id, text, clock.now_iso()),
        )
        self.conn.commit()

    def recent_openers(self, n: int = 5) -> list[str]:
        rows = self.conn.execute("SELECT opener_text FROM openers ORDER BY id DESC LIMIT ?", (n,))
        return [r[0] for r in rows]

    # ---------- activity ----------
    def log(self, command: str, event: str, person_id: int | None = None, detail: str | None = None) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}")
        self.conn.execute(
            "INSERT INTO activity_log (timestamp, command, event, person_id, detail) VALUES (?, ?, ?, ?, ?)",
            (clock.now_iso(), command, event, person_id, (detail or "")[:500]),
        )
        self.conn.commit()

    def count_events(self, event: str, since_iso: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM activity_log WHERE event = ? AND timestamp >= ?", (event, since_iso)
        ).fetchone()
        return int(row[0])

    def activity(self, limit: int = 500) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- maintenance ----------
    def purge(self, older_than_days: int) -> int:
        cutoff = clock.days_ago_iso(older_than_days)
        ids = [
            r[0]
            for r in self.conn.execute(
                "SELECT id FROM people WHERE status IN ('dead', 'skipped') AND COALESCE(updated_at, collected_at) < ? "
                "AND id NOT IN (SELECT person_id FROM picks)",  # a Person with Picks keeps their history
                (cutoff,),
            )
        ]
        for pid in ids:
            self.conn.execute("DELETE FROM activity_log WHERE person_id = ?", (pid,))
            self.conn.execute("DELETE FROM status_history WHERE person_id = ?", (pid,))
            self.conn.execute("DELETE FROM openers WHERE person_id = ?", (pid,))
            self.conn.execute("DELETE FROM people WHERE id = ?", (pid,))
        self.conn.commit()
        return len(ids)
