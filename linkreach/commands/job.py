"""linkreach job: paste a Job description and profile links; get an email draft and a
Connection note for each Pick.

The terminal steps (read the description, confirm the Job, confirm the Picks) happen
here; the work after that is `jobflow.process_job`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.markup import escape

from linkreach import jobflow, jobsearch, llm, logsetup, sanitize
from linkreach.claude_code import ClaudeCodeError
from linkreach.commands.common import EXIT_CONFIG, EXIT_OK, Ctx, console, handle_run_errors
from linkreach.config import MAX_PICK_TARGET
from linkreach.jobdraft import JobFields, clean_description, extract_job
from linkreach.jobsearch import FoundPick

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


@dataclass
class Choice:
    """One entry on the confirmation list: a Supplied pick (found is None) or a Found pick."""

    url: str
    found: FoundPick | None = None


def _add_choices(text: str, choices: list[Choice]) -> None:
    """Pasted links become Supplied picks, listed after the other Supplied ones."""
    urls = [c.url for c in choices]
    before = len(urls)
    _add_links(text, urls)
    supplied = [c for c in choices if c.found is None] + [Choice(u) for u in urls[before:]]
    choices[:] = supplied + [c for c in choices if c.found is not None]


def _show_choice(ctx: Ctx, i: int, c: Choice) -> None:
    if c.found is None:
        console.print(f"  {i}. {escape(c.url)}  [dim]supplied[/]", soft_wrap=True)
    else:
        f = c.found
        tags = f"found · {f.tier_label}" + (" · alumni" if f.alumni else "")
        console.print(f"  {i}. [bold]{escape(f.name)}[/], {escape(f.title)}  [cyan]{escape(tags)}[/]", soft_wrap=True)
        console.print(f"     {escape(c.url)}", soft_wrap=True)
        console.print(f"     why: {escape(f.reason)}", soft_wrap=True)
    for flag in jobflow.contact_flags(ctx.db, c.url):
        console.print(f"     [yellow]{escape(flag)}[/] (kept unless you remove it)", soft_wrap=True)


def confirm_picks(ctx: Ctx, choices: list[Choice]) -> list[Choice]:
    """Supplied picks first, then Found picks with tier and reason. The user removes and
    adds before any profile is read."""
    choices = [c for c in choices if c.found is None] + [c for c in choices if c.found is not None]
    while True:
        if not choices:
            ans = _ask(ctx, "No Picks yet. Paste a link to add, or press Enter to stop: ")
            if not ans.strip():
                return []
            _add_choices(ans, choices)
            continue
        console.print(f"[bold]Picks ({len(choices)}):[/]")
        for i, c in enumerate(choices, start=1):
            _show_choice(ctx, i, c)
        ans = _ask(ctx, "Enter to start, -N to remove Pick N, paste a link to add, q to quit: ").strip()
        if not ans:
            return choices
        if ans.lower() == "q":
            raise Quit()
        if ans.startswith("-") and ans[1:].strip().isdigit():
            n = int(ans[1:].strip())
            if 1 <= n <= len(choices):
                console.print(f"  removed {escape(choices.pop(n - 1).url)}")
            else:
                console.print(f"  [yellow]no Pick number {n}[/]")
            continue
        _add_choices(ans, choices)


def ask_company_page(ctx: Ctx, company: str) -> str | None:
    """The LinkedIn company page to search, confirmed by the user before any page view.
    Offers the page used last time for this company, else a guess from the name.
    Returns the slug, or None to skip the search."""
    default = ctx.db.get_company_slug(company) or jobflow.guess_company_slug(company)
    console.print(
        f"To find more Picks, linkreach searches the current employees of {escape(company)}'s LinkedIn page. "
        "Press Enter to keep the page shown, paste the right company page link, or type - to skip the search."
    )
    for _ in range(COMPANY_TRIES):
        shown = jobflow.company_page_url(default) if default else ""
        ans = _ask(ctx, f"  Company page [{shown}]: ").strip()
        if ans == "-":
            return None
        if not ans:
            if default:
                return default
            continue
        slug = jobflow.parse_company_page(ans)
        if slug:
            return slug
        console.print("  [yellow]That isn't a LinkedIn company page link (like https://www.linkedin.com/company/contoso/).[/]")
    return None


def search(ctx: Ctx, fields: JobFields, urls: list[str], need: int, client: Any) -> tuple[list[FoundPick], int | None]:
    """Run the search for `need` Found picks. Returns (found, None) to carry on, or
    ([], exit code) when a stop ended the run before anything was saved."""
    slug = ask_company_page(ctx, fields.company)
    if slug is None:
        console.print("No search; going on with the links you gave.")
        return [], None
    job = {"company": fields.company, "role_title": fields.role_title, "team": fields.team, "location": fields.location}
    holder: dict[str, jobsearch.SearchOutcome] = {}

    def work() -> int:
        holder["out"] = jobflow.search_found_picks(ctx, job, slug, need, set(urls), client)
        return EXIT_OK

    console.print(f"Searching for up to {need} more Pick{'s' if need != 1 else ''} at {escape(fields.company)}...")
    code = handle_run_errors(ctx, jobflow.COMMAND, work)
    out = holder.get("out")
    if out is None:
        console.print("Stopped during the search. Nothing was saved.")
        return [], code
    if not out.company_id:
        console.print(
            f"[yellow]Couldn't read the company id from {escape(jobflow.company_page_url(slug))}, so no search was run.[/] "
            "Check the company page link next time."
        )
        return [], None
    ctx.db.set_company_slug(fields.company, slug)
    size = f"{out.employees:,} employees" if out.employees is not None else "size unknown"
    console.print(
        f"Ran {out.searches} search{'es' if out.searches != 1 else ''} ({size}); "
        f"{out.cards} new people considered, {len(out.picks)} picked."
    )
    if not out.small_company:
        console.print(f"  CTO and CEO left out: only considered at companies with {jobsearch.SMALL_COMPANY_MAX} or fewer employees.")
    if out.ranked_by == "titles":
        console.print("  [yellow]Claude couldn't rank them, so they're ordered by title alone.[/]")
    if len(out.picks) < need:
        console.print(f"  [yellow]Found {len(out.picks)} of the {need} wanted.[/]")
    return out.picks, None


def _client(ctx: Ctx) -> Any:
    return ctx.claude_client if ctx.claude_client is not None else llm.make_client(ctx.cfg)


def run(ctx: Ctx, file: Path | None = None, picks: int | None = None) -> int:
    target = ctx.cfg.pick_target if picks is None else picks
    if not 0 <= target <= MAX_PICK_TARGET:
        console.print(f"[red]--picks must be between 0 and {MAX_PICK_TARGET}.[/]")
        return EXIT_CONFIG
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

    urls = collect_links(ctx)
    choices = [Choice(u) for u in urls]
    need = target - len(urls)
    if need > 0:
        found, stop_code = search(ctx, confirmed, urls, need, client)
        if stop_code is not None:
            return stop_code
        choices += [Choice(f.profile_url, f) for f in found]
    elif urls:
        console.print(f"Your {len(urls)} link{'s meet' if len(urls) != 1 else ' meets'} the Pick target of {target}; no search needed.")

    try:
        choices = confirm_picks(ctx, choices)
    except Quit:
        console.print("Quit before reading any profile. Nothing was saved.")
        return EXIT_OK
    if not choices:
        console.print("No Picks, so nothing to read or draft. Nothing was saved.")
        return EXIT_OK

    job_id = jobflow.create_job(ctx.db, confirmed, description)
    jobflow.add_supplied_picks(ctx.db, job_id, [c.url for c in choices if c.found is None])
    jobflow.add_found_picks(ctx.db, job_id, [c.found for c in choices if c.found is not None])
    console.print(f"Job #{job_id} saved: {escape(confirmed.role_title or 'role')} at {escape(confirmed.company)}.")

    report = jobflow.JobReport(job_id=job_id)

    def show(r: jobflow.PickResult) -> None:
        tag = {"drafted": "[green]drafted[/]", "no_email": "[green]drafted[/] (no email)"}.get(r.status, "[red]not drafted[/]")
        console.print(f"{tag} {escape(r.name)}")
        for w in r.warnings:
            console.print(f"  [yellow]warning:[/] {escape(w)}", soft_wrap=True)

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
        for w in r.warnings:
            console.print(f"[yellow]warning:[/] {escape(w)}", soft_wrap=True)
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
