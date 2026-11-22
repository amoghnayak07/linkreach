"""linkreach redraft: rescue the Picks `job` couldn't finish.

- A `needs_detail` Pick (its draft failed validation 3 times) is shown with the reasons;
  the user types one line of context, and Claude redrafts it from what's saved. A draft
  that passes goes through the same `jobflow.finish_pick` path as `job` (Gmail draft with
  an email, `no_email` without); one that fails again stays `needs_detail`.
- A Pick whose draft passed but whose Gmail draft failed is retried without asking.

No browser is opened and nothing is revealed: everything comes from the database.
"""

from __future__ import annotations

from typing import Any

from rich.markup import escape

from linkreach import jobflow
from linkreach.commands.common import EXIT_CONFIG, EXIT_OK, Ctx, console, run_end, run_start
from linkreach.commands.job import print_note, result_tag, setup, show_result
from linkreach.commands.misc import job_label

COMMAND = "redraft"


def _ask(ctx: Ctx, prompt: str) -> str:
    try:
        return ctx.input_fn(prompt)
    except EOFError:
        return "q"


def _ask_detail(ctx: Ctx) -> str | None:
    """A cleaned line of context, "" to skip this Pick, or None to quit."""
    while True:
        ans = _ask(ctx, "  One line of context (Enter to skip, q to quit): ").strip()
        if not ans:
            return ""
        if ans.lower() == "q":
            return None
        try:
            detail = jobflow.clean_user_detail(ans)
        except jobflow.BadDetail as exc:
            console.print(f"  [yellow]Can't use that line: {escape(str(exc))}. Try again.[/]")
            continue
        if detail:
            return detail


def run(ctx: Ctx, job_id: int | None = None) -> int:
    db = ctx.db
    if job_id is not None and db.get_job(job_id) is None:
        console.print(f"[red]No Job #{job_id}.[/]")
        return 1
    retry = [r for r in db.picks(job_id, jobflow.RETRYABLE_STATUSES) if jobflow.gmail_pending(r)]
    needs = [r for r in db.picks(job_id, ["needs_detail"]) if not jobflow.gmail_pending(r)]
    if not retry and not needs:
        console.print("No Picks need detail, and no Gmail drafts are waiting. Nothing to do.")
        return EXIT_OK
    ready = setup(ctx, COMMAND)
    if ready is None:
        return EXIT_CONFIG
    style, client, mail = ready

    run_start(db, COMMAND, f"start needs_detail={len(needs)} gmail_retry={len(retry)}")
    counts = {"redrafted": 0, "still": 0, "skipped": 0, "gmail": 0}
    try:
        if retry:
            console.print(f"[bold]Retrying {len(retry)} Gmail draft{'s' if len(retry) != 1 else ''}[/]")
            for row in retry:
                r = jobflow.retry_gmail(ctx, int(row["id"]), mail)
                show_result(r)
                counts["gmail"] += 1 if r.gmail_draft_id else 0
        quit_at = _walk_needs_detail(ctx, needs, client, style, mail, counts)
    except KeyboardInterrupt:
        run_end(db, COMMAND, "interrupted")
        console.print("\n[yellow]Interrupted. Every Pick finished so far is saved.[/]")
        return 130
    run_end(db, COMMAND, "ok")
    console.print()
    console.print(
        f"[bold]Summary:[/] redrafted {counts['redrafted']}, still needs detail {counts['still']}, "
        f"skipped {counts['skipped'] + quit_at}, Gmail drafts {counts['gmail']}",
        soft_wrap=True,
    )
    return EXIT_OK


def _walk_needs_detail(ctx: Ctx, needs: list[Any], client: Any, style: str, mail: Any, counts: dict[str, int]) -> int:
    """Ask for context on each `needs_detail` Pick. Returns how many were left when the
    user quit."""
    if needs:
        console.print(
            f"[bold]{len(needs)} Pick{'s need' if len(needs) != 1 else ' needs'} detail.[/] "
            'Add one line about how you know the person or their work (e.g. "spoke at Grace Hopper about AI hiring").'
        )
    for i, row in enumerate(needs):
        console.print(f"\n[bold]Pick #{row['id']} {escape(row['name'])}[/], {escape(job_label(row['job_id'], row['job_role'], row['job_company']))}", soft_wrap=True)
        console.print(escape(row["profile_url"]), soft_wrap=True)
        console.print(f"[yellow]why:[/] {escape(row['validation_errors'] or 'draft failed')}", soft_wrap=True)
        detail = _ask_detail(ctx)
        if detail is None:
            return len(needs) - i
        if not detail:
            counts["skipped"] += 1
            console.print("  skipped")
            continue
        r = jobflow.redraft_pick(ctx, int(row["id"]), detail, client, style, mail)
        console.print(result_line(r))
        if r.status == "needs_detail" and not r.gmail_pending:
            counts["still"] += 1
            console.print(f"  [yellow]still needs detail:[/] {escape(r.problem)}", soft_wrap=True)
            continue
        counts["redrafted"] += 1
        counts["gmail"] += 1 if r.gmail_draft_id else 0
        print_note(r)
    return 0


def result_line(r: jobflow.PickResult) -> str:
    return f"  {result_tag(r)} {escape(r.name)}"
