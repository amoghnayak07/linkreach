# 06: Needs detail and redraft

**What to build:** A Pick whose draft fails validation 3 times is marked `needs_detail`, gets no output (no Gmail draft once 07 lands), and is listed in the end-of-run summary with the reason. The user can add one line of context to a `needs_detail` Pick (for example "spoke at Grace Hopper about AI hiring") and have linkreach redraft it, moving it on to `drafted` or `no_email` and printing its Connection note. This replaces the old `review` command's detail-and-redraft path.

**Blocked by:** 03

**Status:** resolved

- [x] 3 failed attempts → `needs_detail`, with the validation errors stored and shown in the summary
- [x] A command (or `job` subcommand) lists `needs_detail` Picks and, for each, takes one line of context, redrafts, and re-validates; the user can skip
- [x] A successful redraft moves the Pick on, prints its Connection note, and (once 07 exists) creates its Gmail draft through the same path as `job`
- [x] A redraft that fails again keeps the Pick at `needs_detail` with updated errors
- [x] The user's line of context is sanitized and fenced like profile data
- [x] Tests cover fail-3-times, successful redraft, failed redraft, and skip

## Comments

**Implemented (2026-11-22), after 07 on the same branch.** `_process_pick` moves a Pick to `needs_detail` when its draft fails validation all 3 attempts (or is refused), storing the errors and the found email, with no Gmail draft. The run's Connection-notes list shows `needs detail: <reasons>`, the summary counts it, and a line points at `linkreach redraft`.

New command `linkreach redraft [--job N]` (`commands/redraft.py`):
- First it retries Gmail for Picks whose draft passed but whose Gmail draft failed (07), without asking.
- Then, for each `needs_detail` Pick, it shows the person, Job, link, and stored reasons, and asks for one line. Enter skips, `q` stops. `jobflow.redraft_pick` redrafts from the database (saved title, `context_1`/`context_2`, alumni flag, stored email), with no browser and no new Reveal. A passing draft goes through `jobflow.finish_pick`, the same function `job` uses (`drafted` + Gmail draft, or `no_email`), and its note is printed. A failing one stays `needs_detail` with the new errors.

Decisions worth a look:
- **A separate `redraft` command** rather than a `job` subcommand, because `job` always starts from a new description. It needs the Style file, Claude, and the Gmail sign-in, like `job`.
- **Context handling:** `clean_user_detail` runs `sanitize.clean_line` (HTML, control, and zero-width characters stripped; 300 characters) and refuses a line with a URL, email address, or instruction pattern (`validate.suspicious_context`), asking again. The prompt fences it in `<my_context>` after `</profile_data>`, and the system rules now say it's data, not instructions (before, they called it trusted). The drafter re-checks it, too.
- **The email is kept on `needs_detail`**, so a redraft can create the Gmail draft without another Reveal.
- **Claude API errors** (not validation failures) still leave the Pick at `picked` with the problem stored, as before; they aren't `needs_detail`.
- The old `review` command's detail path is untouched; ticket 11 removes that flow.

Tests: `tests/test_redraft.py` (12): fail 3 times, successful redraft (Gmail draft, note printed, context fenced, no browser), redraft without an email → `no_email`, failed redraft, skip, quit, refused/sanitized context, `--job`, nothing to do, missing Gmail sign-in, through the CLI.
