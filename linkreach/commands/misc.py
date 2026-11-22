"""Small commands: mark, list, export, purge, init, login, set-key, gmail-login.

`mark` and `list` work on Picks (`mark_pick`, `list_picks`). The person-level `mark` and
`list_people` stay for the dormant connection-request path (ADR-0001)."""

from __future__ import annotations

import csv
import getpass
import re
import shutil
import webbrowser
from pathlib import Path
from typing import Any, Callable

from rich.markup import escape
from rich.table import Table

from linkreach import credentials, paths
from linkreach.commands.common import EXIT_CONFIG, Ctx, console
from linkreach.db import DB, STATUSES, TransitionError

MARK_CHOICES = ["accepted", "followed_up", "replied", "meeting", "referral", "dead"]
EXPORT_COLUMNS = [
    "id", "name", "title", "company", "profile_url", "bucket", "is_alumni", "status",
    "job_title", "context_1", "context_2", "note_draft", "note_sent", "followup_draft",
    "collected_at", "sent_at", "accepted_at", "follow_up_date", "followed_up_at", "my_notes",
]


def mark(ctx: Ctx, person_id: int, status: str) -> int:
    try:
        ctx.db.set_status(person_id, status, source="cli", manual=True, follow_up_days=ctx.cfg.follow_up_delay_days)
    except TransitionError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        return 1
    row = ctx.db.get(person_id)
    console.print(f"#{person_id} {escape(row['name'])} is now [bold]{status}[/]")
    return 0


def job_label(job_id: int, role: str | None, company: str | None) -> str:
    return f"Job #{job_id} {role or 'role'} at {company or '?'}"


def mark_pick(ctx: Ctx, pick_id: int, status: str) -> int:
    """`linkreach mark`: record outreach the user did outside linkreach on one Pick."""
    row = ctx.db.get_pick(pick_id)
    if row is None:
        console.print(f"[red]No Pick #{pick_id}. `linkreach list` shows Pick ids.[/]")
        return 1
    if row["status"] == status:
        console.print(f"Pick #{pick_id} {escape(row['name'])} is already [bold]{status}[/]; nothing changed.")
        return 0
    try:
        ctx.db.set_pick_status(pick_id, status, source="cli", manual=True)
    except TransitionError as exc:
        console.print(f"[red]Pick #{pick_id}: {escape(str(exc))}[/]", soft_wrap=True)
        return 1
    console.print(f"Pick #{pick_id} {escape(row['name'])} is now [bold]{status}[/]")
    return 0


def list_picks(ctx: Ctx, job_id: int | None = None, status: str | None = None) -> int:
    """`linkreach list`: Picks, optionally for one Job and one status."""
    if job_id is not None and ctx.db.get_job(job_id) is None:
        console.print(f"[red]No Job #{job_id}.[/]")
        return 1
    rows = ctx.db.picks(job_id, [status] if status else None)
    t = Table(show_lines=False)
    for col in ("pick", "job", "person", "status", "email"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            str(r["id"]),
            escape(job_label(r["job_id"], r["job_role"], r["job_company"])),
            escape(r["name"]),
            r["status"],
            "found" if r["email"] else "",
        )
    console.print(t)
    console.print(f"{len(rows)} picks")
    return 0


def list_people(ctx: Ctx, status: str | None = None) -> int:
    rows = ctx.db.people([status] if status else None)
    t = Table(show_lines=False)
    for col in ("id", "name", "company", "bucket", "alumni", "status", "sent", "accepted", "follow-up"):
        t.add_column(col)
    for r in rows:
        t.add_row(
            str(r["id"]), escape(r["name"]), escape(r["company"]), escape(r["bucket"] or ""),
            "yes" if r["is_alumni"] else "", r["status"], (r["sent_at"] or "")[:10],
            (r["accepted_at"] or "")[:10], r["follow_up_date"] or "",
        )
    console.print(t)
    console.print(f"{len(rows)} people")
    return 0


def csv_safe(value: object) -> str:
    """Neutralize spreadsheet formula injection from scraped text."""
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@\t\r":
        return "'" + s
    return s


def export(ctx: Ctx, out: Path | None = None) -> int:
    out = out or Path.cwd() / "linkreach_export.csv"
    rows = ctx.db.people()
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(EXPORT_COLUMNS)
        for r in rows:
            w.writerow([csv_safe(r[c]) for c in EXPORT_COLUMNS])
    paths.secure_file(out)
    console.print(f"Wrote {len(rows)} people to {out}")
    return 0


def parse_age(value: str) -> int:
    m = re.fullmatch(r"(\d+)\s*d", value.strip().lower())
    if not m:
        raise ValueError("use a number of days like 180d")
    return int(m.group(1))


def purge(db: DB, older_than: str) -> int:
    try:
        days = parse_age(older_than)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        return EXIT_CONFIG
    n = db.purge(days)
    console.print(f"Purged {n} people marked dead or skipped (older than {days} days), plus their log rows.")
    return 0


def init(directory: Path) -> int:
    """Copy example inputs into the current folder without overwriting anything."""
    src = Path(__file__).resolve().parent.parent / "examples"
    created = []
    for name, target in (
        ("config.example.yaml", "config.yaml"),
        ("companies.example.csv", "companies.csv"),
        ("jobs.example.csv", "jobs.csv"),
        ("style.example.md", paths.STYLE_FILE),
    ):
        dest = directory / target
        if dest.exists():
            console.print(f"exists, left alone: {dest}")
            continue
        shutil.copyfile(src / name, dest)
        created.append(dest)
    paths.ensure_home()
    for p in created:
        console.print(f"created {p}")
    console.print(f"private data folder: {paths.home()}")
    return 0


def set_key() -> int:
    key = getpass.getpass("Paste your Anthropic API key (input hidden): ").strip()
    if not key.startswith("sk-ant-"):
        console.print("[red]That doesn't look like an Anthropic API key.[/]")
        return 1
    try:
        credentials.store_in_keyring(key)
    except Exception as exc:
        console.print(f"[red]Could not store in the OS keychain ({type(exc).__name__}). Use a .env file instead.[/]")
        return 1
    console.print("Stored in the OS keychain under service 'linkreach'.")
    return 0


def gmail_login(client_file: Path, open_browser: Callable[[str], Any] | None = None) -> int:
    """`linkreach gmail-login`: sign in to Gmail with the user's own OAuth desktop client,
    compose scope only; the refresh token goes to the OS keychain and nowhere else."""
    from linkreach import gmail

    def show_and_open(url: str) -> None:
        console.print("Opening Google's sign-in page in your browser. If it doesn't open, copy this link into it:")
        console.print(url, soft_wrap=True, markup=False)
        (open_browser or webbrowser.open)(url)

    console.print(
        "linkreach asks only for the gmail.compose scope: it can create drafts in your Gmail, "
        "and it never sends them. You review and send each draft yourself."
    )
    try:
        gmail.login(client_file, show_and_open)
    except gmail.LoginError as exc:
        console.print(f"[red]Gmail sign-in failed: {escape(str(exc))}[/]")
        return 1
    except Exception as exc:  # keychain unavailable, etc.
        console.print(f"[red]Couldn't store the Gmail sign-in in the OS keychain ({type(exc).__name__}).[/]")
        return 1
    console.print("[green]Gmail signed in.[/] The sign-in is stored in the OS keychain under service 'linkreach'.")
    return 0


def login(ctx: Ctx) -> int:
    """Open the dedicated profile so you can sign in to LinkedIn by hand, once."""
    from linkreach import selectors as S

    console.print(
        "Opening Chrome on the dedicated linkreach profile.\n"
        "Sign in to LinkedIn there yourself. linkreach never sees or stores your password.\n"
        "When your feed loads, close that Chrome window to continue. Use this profile for LinkedIn only."
    )
    ctx.open_chrome(ctx.cfg.profile_path, S.LOGIN_URL)

    session = ctx.session_factory(ctx.cfg)
    try:
        session.goto(S.FEED_URL)
        url = (session.url or "").lower()
        ok = not any(p in url for p in S.LOGGED_OUT_URL_PARTS) and session.exists(S.LOGGED_IN_MARKERS, timeout_ms=8000)
        console.print("[green]Signed in.[/]" if ok else "[red]Still not signed in. Run `linkreach login` again.[/]")
        return 0 if ok else 1
    finally:
        session.close()


def statuses_help() -> str:
    return ", ".join(STATUSES)
