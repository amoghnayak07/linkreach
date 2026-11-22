"""linkreach job: paste a Job description and profile links; get an email draft and a
Connection note for each Pick.

The terminal steps (read the description, confirm the Job, confirm the Picks) happen
here; the work after that is `jobflow.process_job`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.markup import escape

from linkreach import jobflow, llm, logsetup, sanitize
from linkreach.claude_code import ClaudeCodeError
from linkreach.commands.common import EXIT_CONFIG, EXIT_OK, Ctx, console, handle_run_errors
from linkreach.jobdraft import JobFields, clean_description, extract_job

log = logsetup.get("job")

END_MARKER = "END"
MAX_LINES = 3000
COMPANY_TRIES = 3


class Quit(Exception):
    pass


def _ask(ctx: Ctx, prompt: str) -> str:
    try:
        return ctx.input_fn(prompt)
    except EOFError:
        return ""


def read_description(ctx: Ctx, file: Path | None) -> str | None:
    if file is not None:
        try:
            return file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            console.print(f"[red]Can't read {escape(str(file))}: {escape(exc.strerror or type(exc).__name__)}[/]")
            return None
    console.print(f"Paste the job description. When you're done, type [bold]{END_MARKER}[/] on its own line and press Enter.")
    lines: list[str] = []
    for _ in range(MAX_LINES):
        try:
            line = ctx.input_fn("")
        except EOFError:
            break
        if line.strip().upper() == END_MARKER:
            break
        lines.append(line)
    return "\n".join(lines)


def confirm_fields(ctx: Ctx, fields: JobFields) -> JobFields | None:
    """Show what was extracted; Enter keeps a value, typing replaces it. A missing company
    is always asked for; linkreach never guesses it."""
    console.print("[bold]This is the job I read.[/] Press Enter to keep a value, or type a correction.")
    for label, attr in (("Company", "company"), ("Role", "role_title"), ("Team", "team"), ("Location", "location")):
        current = getattr(fields, attr)
        if attr == "company" and not current:
            continue
        ans = sanitize.clean_line(_ask(ctx, f"  {label} [{current}]: "), 150)
        if ans:
            setattr(fields, attr, ans)
    for _ in range(COMPANY_TRIES):
        if fields.company:
            break
        fields.company = sanitize.clean_line(_ask(ctx, "  Company (the description doesn't name one): "), 150)
    if not fields.company:
        console.print("[red]No company given; stopping. Nothing was saved.[/]")
        return None
    return fields


def collect_links(ctx: Ctx) -> list[str]:
    console.print(
        "Paste LinkedIn profile links for people you've already researched, one or more per line. "
        "Press Enter on an empty line when done."
    )
    urls: list[str] = []
    while True:
        line = _ask(ctx, "  link: ")
        if not line.strip():
            return urls
        _add_links(line, urls)


def _add_links(text: str, urls: list[str]) -> None:
    for raw in jobflow.split_links(text):
        url = jobflow.parse_profile_link(raw)
        if url is None:
            console.print(f"  [yellow]not a LinkedIn profile link, skipped:[/] {escape(raw[:120])}")
        elif url in urls:
            console.print(f"  already listed: {escape(url)}")
        else:
            urls.append(url)


def confirm_links(ctx: Ctx, urls: list[str]) -> list[str]:
    """Let the user remove and add links before any profile is read."""
    while True:
        if not urls:
            ans = _ask(ctx, "No profile links yet. Paste a link to add, or press Enter to stop: ")
            if not ans.strip():
                return []
            _add_links(ans, urls)
            continue
        console.print(f"[bold]Picks ({len(urls)}):[/]")
        for i, u in enumerate(urls, start=1):
            console.print(f"  {i}. {escape(u)}", soft_wrap=True)
            for flag in jobflow.contact_flags(ctx.db, u):
                console.print(f"     [yellow]{escape(flag)}[/] (kept unless you remove it)", soft_wrap=True)
        ans = _ask(ctx, "Enter to start, -N to remove link N, paste a link to add, q to quit: ").strip()
        if not ans:
            return urls
        if ans.lower() == "q":
            raise Quit()
        if ans.startswith("-") and ans[1:].strip().isdigit():
            n = int(ans[1:].strip())
            if 1 <= n <= len(urls):
                console.print(f"  removed {escape(urls.pop(n - 1))}")
            else:
                console.print(f"  [yellow]no Pick number {n}[/]")
            continue
        _add_links(ans, urls)


def _client(ctx: Ctx) -> Any:
    return ctx.claude_client if ctx.claude_client is not None else llm.make_client(ctx.cfg)


def run(ctx: Ctx, file: Path | None = None) -> int:
    try:
        style = jobflow.load_style()
    except jobflow.StyleMissing as exc:
        console.print(f"[bold red]linkreach job needs your Style file:[/] {escape(str(exc))}")
        return EXIT_CONFIG
    try:
        client = _client(ctx)
    except RuntimeError as exc:
        console.print(f"[red]{escape(str(exc))}[/]")
        return EXIT_CONFIG

    raw = read_description(ctx, file)
    if raw is None:
        return EXIT_CONFIG
    description = clean_description(raw)
    if not description:
        console.print("[red]The job description is empty; nothing to do.[/]")
        return EXIT_CONFIG

    try:
        fields = extract_job(client, ctx.cfg, description)
    except Exception as exc:  # the user can still type every field
        logsetup.event(log, "job extraction failed", error=type(exc).__name__)
        # A Claude Code error message never holds prompt or output text, so it's safe to show.
        why = str(exc) if isinstance(exc, ClaudeCodeError) else type(exc).__name__
        console.print(f"[yellow]Couldn't read the job description with Claude ({escape(why)}); please type the details.[/]")
        fields = JobFields()
    confirmed = confirm_fields(ctx, fields)
    if confirmed is None:
        return EXIT_CONFIG

    try:
        urls = confirm_links(ctx, collect_links(ctx))
    except Quit:
        console.print("Quit before reading any profile. Nothing was saved.")
        return EXIT_OK
    if not urls:
        console.print("No Picks, so nothing to read or draft. Nothing was saved.")
        return EXIT_OK

    job_id = jobflow.create_job(ctx.db, confirmed, description)
    jobflow.add_supplied_picks(ctx.db, job_id, urls)
    console.print(f"Job #{job_id} saved: {escape(confirmed.role_title or 'role')} at {escape(confirmed.company)}.")

    report = jobflow.JobReport(job_id=job_id)

    def show(r: jobflow.PickResult) -> None:
        tag = {"drafted": "[green]drafted[/]", "no_email": "[green]drafted[/] (no email)"}.get(r.status, "[red]not drafted[/]")
        console.print(f"{tag} {escape(r.name)}")

    def work() -> int:
        jobflow.process_job(ctx, job_id, report, client, style, ctx.email_finder, on_pick=show)  # type: ignore[arg-type]
        return EXIT_OK

    code = handle_run_errors(ctx, jobflow.COMMAND, work)
    print_report(report)
    return code


def print_report(report: jobflow.JobReport) -> None:
    console.print()
    console.print("[bold]Connection notes[/] (copy each into LinkedIn yourself):")
    for r in report.results:
        console.print(f"\n[bold]{escape(r.name)}[/]", soft_wrap=True)
        console.print(escape(r.profile_url), soft_wrap=True)
        if r.note:
            console.print(escape(r.note), soft_wrap=True)
        else:
            console.print(f"[red]no draft:[/] {escape(r.problem or 'not finished')}", soft_wrap=True)
    if not report.results:
        console.print("  (none)")
    not_reached = report.picks_total - len(report.results)
    console.print()
    console.print(
        f"[bold]Summary:[/] Picks {report.picks_total}, drafts {report.drafts}, failures {report.failures}"
        + (f", not reached {not_reached}" if not_reached > 0 else "")
        + f", emails found {report.emails_found}, page views used {report.views_used}",
        soft_wrap=True,
    )
