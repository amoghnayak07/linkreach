"""linkreach sync: revisit sent profiles and mark 1st-degree connections accepted."""

from __future__ import annotations

from rich.markup import escape

from linkreach.commands.common import Ctx, FailStreak, console, handle_run_errors, linkedin_session, refuse_if_manual


def run(ctx: Ctx) -> int:
    refused = refuse_if_manual(ctx, "sync")
    if refused is not None:
        return refused
    rows = ctx.db.people(["sent"])
    rows.sort(key=lambda r: (r["sent_at"] or "", r["id"]))
    if not rows:
        console.print("No sent requests to check.")
        return 0
    return handle_run_errors(ctx, "sync", lambda: _sync(ctx, rows))


def _sync(ctx: Ctx, rows: list) -> int:
    accepted = 0
    with linkedin_session(ctx, "sync") as li:
        streak = FailStreak(li, "sync")
        for row in rows:
            pid = int(row["id"])
            profile = li.read_profile(row["profile_url"], pid)
            if not profile.ok:
                streak.fail(pid, profile.missing)
                continue
            streak.ok()
            if profile.first_degree:
                ctx.db.set_status(pid, "accepted", source="sync", follow_up_days=ctx.cfg.follow_up_delay_days)
                accepted += 1
                console.print(f"[green]accepted[/] {escape(row['name'])} ({escape(row['company'])})")
    console.print(f"[bold]{accepted} newly accepted.[/] Follow-ups are due {ctx.cfg.follow_up_delay_days} days after acceptance.")
    return 0
