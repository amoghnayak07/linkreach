"""Shared plumbing for commands that open LinkedIn."""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from rich.console import Console

from linkreach import clock, logsetup, paths
from linkreach.browser import PlaywrightSession, Session, open_plain_chrome
from linkreach.config import Config, Inputs
from linkreach.db import DB
from linkreach.linkedin import LinkedIn
from linkreach.safety import CapReached, DomainViolation, SelectorBroken, StopRun

console = Console(highlight=False)
log = logsetup.get("run")

SessionFactory = Callable[[Config], Session]

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_STOPPED = 3
EXIT_SELECTORS = 5
EXIT_DOCTOR = 6
EXIT_REFUSED = 7


def playwright_factory(cfg: Config) -> Session:
    return PlaywrightSession(cfg.profile_path, channel=cfg.chrome_channel, headless=cfg.headless)


@dataclass
class Ctx:
    inputs: Inputs
    db: DB
    session_factory: SessionFactory = playwright_factory
    sleep: Callable[[float], None] = time.sleep
    input_fn: Callable[[str], str] = input
    api_check: Callable[[str], tuple[bool, str]] | None = None  # doctor's API-key check (tests inject one)
    drafter: object | None = None  # drafting.Drafter (tests inject one with a fake client)
    open_chrome: Callable[[Path, str], int] = open_plain_chrome  # login's plain-Chrome window

    @property
    def cfg(self) -> Config:
        return self.inputs.config


CONNECT_COMMANDS = ("send", "sync")


def refuse_if_manual(ctx: Ctx, command: str) -> int | None:
    """ADR-0001: `send` and `sync` only run with `connect_mode: automated`.
    Returns an exit code to refuse with, or None when the command may run."""
    if ctx.cfg.connect_mode == "automated":
        return None
    ctx.db.log(command, "info", None, "refused: connect_mode is manual")
    console.print(f"[bold red]`linkreach {command}` is switched off.[/] linkreach no longer sends connection requests;")
    console.print("you send them yourself on LinkedIn. To turn the automated path back on, set")
    console.print("[bold]connect_mode: automated[/] in config.yaml (see docs/adr/0001).")
    return EXIT_REFUSED


def run_start(db: DB, command: str, detail: str = "start") -> None:
    db.log(command, "run", None, detail)
    logsetup.event(log, "run start", command=command, detail=detail)


def run_end(db: DB, command: str, detail: str) -> None:
    db.log(command, "run", None, f"end:{detail}")
    logsetup.event(log, "run end", command=command, detail=detail)


@contextmanager
def linkedin_session(ctx: Ctx, command: str, start_detail: str = "start") -> Iterator[LinkedIn]:
    """Open the browser, yield a LinkedIn helper, and translate stop conditions into
    clean exits. Progress is committed per person by the caller."""
    run_start(ctx.db, command, start_detail)
    session: Session | None = None
    try:
        session = ctx.session_factory(ctx.cfg)
        yield LinkedIn(session, ctx.db, ctx.cfg, command, sleep=ctx.sleep)
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def handle_run_errors(ctx: Ctx, command: str, fn: Callable[[], int]) -> int:
    """Run `fn`, mapping safety exceptions to exit codes and log rows."""
    try:
        code = fn()
        run_end(ctx.db, command, "ok")
        return code
    except StopRun as exc:
        run_end(ctx.db, command, f"stopped:{exc.kind}")
        console.print(f"[bold red]STOPPED:[/] LinkedIn showed a {exc.kind} page ({exc.detail}).")
        console.print("No retries. Open LinkedIn yourself, resolve it by hand, and wait before running again.")
        return EXIT_STOPPED
    except DomainViolation as exc:
        ctx.db.log(command, "stop", None, f"domain: {exc}")
        run_end(ctx.db, command, "stopped:domain")
        console.print(f"[bold red]STOPPED:[/] {exc}")
        return EXIT_STOPPED
    except SelectorBroken as exc:
        run_end(ctx.db, command, "stopped:selector_broken")
        console.print(f"[bold red]STOPPED:[/] {exc}")
        console.print("Fix the selectors in linkreach/selectors.py, then run `linkreach doctor`.")
        return EXIT_SELECTORS
    except CapReached as exc:
        run_end(ctx.db, command, f"cap:{exc.which}")
        console.print(f"[yellow]{exc}. Stopping for today.[/]")
        return EXIT_OK
    except KeyboardInterrupt:
        run_end(ctx.db, command, "interrupted")
        console.print("\n[yellow]Interrupted. Progress up to the last person is saved.[/]")
        return 130


class FailStreak:
    """Stops the run after N consecutive selector failures, with a screenshot."""

    def __init__(self, li: LinkedIn, command: str, limit: int = 3):
        self.li = li
        self.command = command
        self.limit = limit
        self.count = 0

    def ok(self) -> None:
        self.count = 0

    def fail(self, person_id: int | None, missing: list[str]) -> None:
        self.count += 1
        if self.count >= self.limit:
            shot = paths.screenshots_dir() / f"selector_broken_{clock.now().strftime('%Y%m%d_%H%M%S')}.png"
            self.li.s.screenshot(shot)
            detail = f"{self.count} profiles in a row; missing {', '.join(missing)}; screenshot {shot.name}"
            self.li.db.log(self.command, "selector_broken", person_id, detail)
            raise SelectorBroken(f"selectors failed on {self.count} profiles in a row ({', '.join(missing)})")
