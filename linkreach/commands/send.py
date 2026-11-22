"""linkreach send: send approved connection requests, within caps.

Duplicate protection: `send_attempted_at` and a `send` activity row are committed
*before* Send is clicked. If the process dies after that point, the next run sees
the marker, checks the profile for the Pending state, and never clicks again.
"""

from __future__ import annotations

from rich.markup import escape
from rich.panel import Panel

from linkreach import clock, logsetup, validate
from linkreach.commands import doctor
from linkreach.commands.common import (
    EXIT_DOCTOR,
    EXIT_REFUSED,
    Ctx,
    FailStreak,
    console,
    handle_run_errors,
    linkedin_session,
    refuse_if_manual,
)
from linkreach.safety import CapReached, brake_status, check_request_caps, in_auto_window

log = logsetup.get("send")


class DoctorFailed(Exception):
    pass


def candidates(ctx: Ctx) -> list:
    rows = ctx.db.people(["approved"])
    rows.sort(
        key=lambda r: (
            0 if r["send_attempted_at"] else 1,  # resolve interrupted attempts first
            0 if r["is_alumni"] else 1,
            r["id"],
        )
    )
    return rows


def run(ctx: Ctx, auto: bool = False, override_brake: bool = False) -> int:
    refused = refuse_if_manual(ctx, "send")
    if refused is not None:
        return refused
    cfg = ctx.cfg
    brake = brake_status(ctx.db, cfg)
    if brake.tripped:
        console.print(
            f"[bold yellow]Acceptance brake tripped:[/] {brake.accepted}/{brake.sample} accepted "
            f"({(brake.rate or 0):.0%}) on requests older than {cfg.brake.age_days} days, "
            f"below {cfg.brake.min_rate:.0%}. Rethink your notes before sending more."
        )
    if auto:
        if not in_auto_window(cfg):
            console.print("[yellow]Outside the auto-send window; not sending.[/]")
            ctx.db.log("send", "info", None, "auto: outside window")
            return EXIT_REFUSED
        if brake.tripped and not override_brake:
            console.print("[bold red]--auto is disabled while the brake is tripped.[/] Use --override-brake to force it.")
            ctx.db.log("send", "stop", None, "auto refused: acceptance brake tripped")
            return EXIT_REFUSED
    try:
        check_request_caps(ctx.db, cfg)
    except CapReached as exc:
        console.print(f"[yellow]{exc}. Nothing sent.[/]")
        return 0
    rows = candidates(ctx)
    if not rows:
        console.print("No approved connection notes to send.")
        return 0

    mode = "auto" if auto else "manual"
    if auto and brake.tripped and override_brake:
        mode = "auto:override_brake"

    def _go() -> int:
        try:
            return _send(ctx, rows, auto, mode)
        except DoctorFailed:
            console.print("[bold red]doctor failed; --auto aborted before sending anything.[/]")
            return EXIT_DOCTOR

    return handle_run_errors(ctx, "send", _go)


def _send(ctx: Ctx, rows: list, auto: bool, mode: str) -> int:
    cfg = ctx.cfg
    db = ctx.db
    sent = failed = skipped = 0
    with linkedin_session(ctx, "send", f"start:{mode}") as li:
        if auto and not doctor.run_with(ctx, li):
            raise DoctorFailed()
        streak = FailStreak(li, "send")
        for r in rows:
            row = db.get(r["id"])
            if row is None or row["status"] != "approved":
                continue
            pid = int(row["id"])
            note = row["note_draft"] or ""
            res = validate.validate_note(
                note,
                resume_url=cfg.resume_url,
                banned_phrases=cfg.banned_phrases,
                note_max_chars=cfg.note_max_chars,
            )
            if not res.ok:
                db.update_fields(pid, validation_errors="\n".join(res.errors))
                db.set_status(pid, "needs_detail")
                console.print(f"[yellow]skip[/] {escape(row['name'])}: draft no longer passes validation")
                continue

            check_request_caps(db, cfg)  # raises CapReached -> clean stop
            recovering = row["send_attempted_at"] is not None
            label = f"{escape(row['name'])} ({escape(row['company'])})"
            profile = li.read_profile(row["profile_url"], pid)
            if not profile.ok:
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, f"profile selectors missing: {', '.join(profile.missing)}")
                failed += 1
                streak.fail(pid, profile.missing)
                continue
            streak.ok()

            if profile.first_degree:
                db.set_status(pid, "accepted", follow_up_days=cfg.follow_up_delay_days)
                db.log("send", "info", pid, "already a 1st-degree connection; no request sent")
                console.print(f"[cyan]already connected[/] {label}")
                continue
            if profile.pending:
                fields = {"sent_at": row["send_attempted_at"] or clock.now_iso()}
                if recovering:
                    fields["note_sent"] = note
                db.set_status(pid, "sent", **fields)
                db.log("send", "info", pid, "Pending already showing; marked sent without clicking")
                console.print(f"[cyan]already pending[/] {label}")
                sent += 1
                continue
            if recovering:
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, "earlier attempt was interrupted and no Pending state shows; not retrying")
                console.print(f"[yellow]failed[/] {label}: earlier attempt unconfirmed, not retrying")
                failed += 1
                continue

            problem = li.open_connect_dialog()
            if problem is not None:
                if problem.outcome == "already_pending":
                    db.set_status(pid, "sent", sent_at=clock.now_iso())
                    sent += 1
                    continue
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, problem.reason)
                console.print(f"[yellow]failed[/] {label}: {escape(problem.reason)}")
                failed += 1
                continue
            if not li.type_note(note):
                li._dismiss()
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, "could not type the note")
                failed += 1
                continue

            if not auto:
                console.print(Panel(escape(note), title=f"{label} — {len(note)} chars", expand=False))
                answer = ctx.input_fn("Press Enter to send, s to skip. ").strip().lower()
                if answer == "s":
                    li._dismiss()
                    db.set_status(pid, "skipped")
                    skipped += 1
                    continue
                if answer == "q":
                    li._dismiss()
                    console.print("Quitting; this person stays approved.")
                    break

            # Commit the attempt BEFORE clicking, so a crash can never cause a second click.
            db.update_fields(pid, send_attempted_at=clock.now_iso())
            db.log("send", "send", pid, f"clicked Send ({'auto' if auto else 'manual'})")
            if not li.click_send():
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, "Send button not found")
                failed += 1
                continue
            if li.confirm_pending():
                db.set_status(pid, "sent", note_sent=note, sent_at=clock.now_iso())
                logsetup.event(log, "request sent", person_id=pid)
                console.print(f"[green]sent[/] {label}")
                sent += 1
            else:
                db.set_status(pid, "failed")
                db.log("send", "fail", pid, "Pending state did not appear after Send")
                console.print(f"[yellow]failed[/] {label}: Pending state did not appear")
                failed += 1
    console.print(f"[bold]Sent {sent}, failed {failed}, skipped {skipped}.[/]")
    return 0
