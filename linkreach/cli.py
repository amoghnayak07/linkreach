"""linkreach command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.markup import escape

from linkreach import __version__, logsetup, paths
from linkreach.commands.common import CONNECT_COMMANDS, EXIT_CONFIG, Ctx, console
from linkreach.config import ConfigError, load_inputs
from linkreach.db import DB, PICK_AUTO_ONLY, PICK_STATUSES

MARK_PICK_CHOICES = [s for s in PICK_STATUSES if s not in PICK_AUTO_ONLY]

# Commands that don't use companies.csv / jobs.csv, so they run without them.
NO_CSV_COMMANDS = {"job", "redraft", "mark", "list"}


def peek_connect_mode(argv: list[str] | None) -> str:
    """Read `connect_mode` from config.yaml before full validation, so help text can
    hide `send` and `sync`. Anything unreadable counts as the default, manual."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--inputs", type=Path)
    known, _ = pre.parse_known_args(argv)
    directory = known.inputs.resolve() if known.inputs else paths.inputs_dir()
    try:
        import yaml

        raw = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    except Exception:
        return "manual"
    if isinstance(raw, dict) and raw.get("connect_mode") == "automated":
        return "automated"
    return "manual"


def build_parser(connect_mode: str = "manual") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="linkreach", description="LinkedIn outreach with hard safety rails.")
    p.add_argument("--version", action="version", version=f"linkreach {__version__}")
    p.add_argument("--inputs", type=Path, help="folder holding config.yaml, companies.csv, jobs.csv (default: current folder)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    sub.add_parser("init", help="copy example config.yaml, style.md, companies.csv, jobs.csv here")
    j = sub.add_parser("job", help="paste a job description and profile links; get an email draft and connection note per Pick")
    j.add_argument("--file", type=Path, help="read the job description from this file instead of pasting it")
    j.add_argument("--picks", type=int, metavar="N", help="Pick target for this run (default: pick_target in config.yaml)")
    r = sub.add_parser("redraft", help="add a line of context to Picks that need detail and redraft them; retry failed Gmail drafts")
    r.add_argument("--job", type=int, help="only this Job id")
    sub.add_parser("set-key", help="store ANTHROPIC_API_KEY in the OS keychain (llm_backend: api only)")
    g = sub.add_parser("gmail-login", help="sign in to Gmail (create-drafts scope only) with your own OAuth desktop client")
    g.add_argument("--client-file", type=Path, required=True, help="the OAuth client .json you downloaded from Google Cloud")
    sub.add_parser("login", help="open the dedicated Chrome profile so you can sign in to LinkedIn by hand")
    c = sub.add_parser("collect", help="find people at each company")
    c.add_argument("--dry-run", action="store_true", help="print planned searches; open nothing")
    sub.add_parser("draft", help="write notes and follow-ups for collected people")
    sub.add_parser("review", help="approve, edit, or skip drafts")
    s = sub.add_parser("send", help="send approved connection requests")
    s.add_argument("--auto", action="store_true", help="click Send without asking (runs doctor first)")
    s.add_argument("--override-brake", action="store_true", help="allow --auto even when the acceptance brake is tripped")
    sub.add_parser("sync", help="mark accepted connections")
    m = sub.add_parser("mark", help="record what you did for a Pick (emailed, connected, replied, meeting, referral, dead)")
    m.add_argument("id", type=int, help="Pick id (see `linkreach list`)")
    # Every Pick status is accepted here so the hand-set guard can explain the refusal.
    m.add_argument("status", choices=PICK_STATUSES, metavar="status", help=", ".join(MARK_PICK_CHOICES))
    ls = sub.add_parser("list", help="print Picks in the terminal, by Job and status")
    ls.add_argument("--job", type=int, help="only this Job id")
    ls.add_argument("--status", choices=PICK_STATUSES)
    d = sub.add_parser("dashboard", help="start the local dashboard on 127.0.0.1:8765")
    d.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    e = sub.add_parser("export", help="write all people to linkreach_export.csv")
    e.add_argument("--out", type=Path)
    sub.add_parser("doctor", help="check selectors, login, Claude access (API key or Claude Code), caps, and DB")
    pg = sub.add_parser("purge", help="delete dead/skipped people older than N days")
    pg.add_argument("--older-than", default="180d", help="age like 180d (default 180d)")
    if connect_mode != "automated":
        # Still parseable (so they can refuse with a clear message), just not listed.
        sub._choices_actions = [a for a in sub._choices_actions if a.dest not in CONNECT_COMMANDS]
    return p


def main(argv: list[str] | None = None, ctx_overrides: dict | None = None) -> int:
    args = build_parser(peek_connect_mode(argv)).parse_args(argv)
    logsetup.setup(args.verbose)
    if args.inputs:
        import os

        os.environ["LINKREACH_INPUTS"] = str(args.inputs.resolve())

    if args.command == "init":
        from linkreach.commands import misc

        return misc.init(paths.inputs_dir())
    if args.command == "set-key":
        from linkreach.commands import misc

        return misc.set_key()
    if args.command == "gmail-login":
        from linkreach.commands import misc

        return misc.gmail_login(args.client_file)

    try:
        inputs = load_inputs(require_csvs=args.command not in NO_CSV_COMMANDS)
    except ConfigError as exc:
        console.print(f"[bold red]linkreach refuses to start: {len(exc.problems)} problem(s) in your input files[/]")
        for prob in exc.problems:
            console.print(f"  - {escape(prob)}")
        return EXIT_CONFIG

    paths.ensure_home()
    db = DB.open()
    ctx = Ctx(inputs=inputs, db=db)
    for k, v in (ctx_overrides or {}).items():
        setattr(ctx, k, v)
    try:
        return _dispatch(args, ctx)
    finally:
        db.close()


def _dispatch(args: argparse.Namespace, ctx: Ctx) -> int:
    cmd = args.command
    if cmd == "job":
        from linkreach.commands import job

        return job.run(ctx, file=args.file, picks=args.picks)
    if cmd == "redraft":
        from linkreach.commands import redraft

        return redraft.run(ctx, job_id=args.job)
    if cmd == "collect":
        from linkreach.commands import collect

        return collect.run(ctx, dry_run=args.dry_run)
    if cmd == "draft":
        from linkreach import drafting
        from linkreach.commands.common import handle_run_errors, run_start

        def _draft() -> int:
            run_start(ctx.db, "draft")
            try:
                drafter = ctx.drafter or drafting.Drafter(ctx.cfg)
                _ = drafter.client  # type: ignore[attr-defined]  # fail fast if no key / no `claude`
            except RuntimeError as exc:
                console.print(f"[red]{exc}[/]")
                return EXIT_CONFIG

            def show(row, outcome):
                tag = {"drafted": "[green]drafted[/]", "needs_detail": "[yellow]needs_detail[/]"}.get(outcome.status, "[red]error[/]")
                console.print(f"{tag} {escape(row['name'])} ({escape(row['company'])})")

            counts = drafting.run_draft(ctx.inputs, ctx.db, drafter, on_result=show)  # type: ignore[arg-type]
            console.print(f"[bold]drafted {counts.get('drafted', 0)}, needs_detail {counts.get('needs_detail', 0)}, errors {counts.get('error', 0)}[/]")
            return 0

        return handle_run_errors(ctx, "draft", _draft)
    if cmd == "review":
        from linkreach.commands import review
        from linkreach.commands.common import handle_run_errors, run_start

        def _review() -> int:
            run_start(ctx.db, "review")
            return review.run(ctx)

        return handle_run_errors(ctx, "review", _review)
    if cmd == "send":
        from linkreach.commands import send

        return send.run(ctx, auto=args.auto, override_brake=args.override_brake)
    if cmd == "sync":
        from linkreach.commands import sync

        return sync.run(ctx)
    if cmd == "doctor":
        from linkreach.commands import doctor

        return doctor.run(ctx)
    if cmd == "login":
        from linkreach.commands import misc

        return misc.login(ctx)
    if cmd == "mark":
        from linkreach.commands import misc

        return misc.mark_pick(ctx, args.id, args.status)
    if cmd == "list":
        from linkreach.commands import misc

        return misc.list_picks(ctx, args.job, args.status)
    if cmd == "export":
        from linkreach.commands import misc

        return misc.export(ctx, args.out)
    if cmd == "purge":
        from linkreach.commands import misc

        return misc.purge(ctx.db, args.older_than)
    if cmd == "dashboard":
        from linkreach.dashboard import server

        try:
            server.serve(ctx.inputs, ctx.db.path, open_browser=not args.no_open)
        except server.PortInUse as exc:
            console.print(f"[red]{exc}[/]")
            return 1
        return 0
    console.print(f"unknown command {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
