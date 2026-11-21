# 06: Needs detail and redraft

**What to build:** A Pick whose draft fails validation 3 times is marked `needs_detail`, gets no output (no Gmail draft once 07 lands), and is listed in the end-of-run summary with the reason. The user can add one line of context to a `needs_detail` Pick (for example "spoke at Grace Hopper about AI hiring") and have linkreach redraft it, moving it on to `drafted` or `no_email` and printing its Connection note. This replaces the old `review` command's detail-and-redraft path.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] 3 failed attempts → `needs_detail`, with the validation errors stored and shown in the summary
- [ ] A command (or `job` subcommand) lists `needs_detail` Picks and, for each, takes one line of context, redrafts, and re-validates; the user can skip
- [ ] A successful redraft moves the Pick on, prints its Connection note, and (once 07 exists) creates its Gmail draft through the same path as `job`
- [ ] A redraft that fails again keeps the Pick at `needs_detail` with updated errors
- [ ] The user's line of context is sanitized and fenced like profile data
- [ ] Tests cover fail-3-times, successful redraft, failed redraft, and skip
