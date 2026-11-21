# 03: First end-to-end slice: `linkreach job` with Supplied picks only

**What to build:** The thinnest complete path through the new flow (ADR-0002, fixed pipeline). The user runs `linkreach job`, pastes a Job description (or passes `--file`), and Claude extracts company, role title, team, and location; the user confirms or corrects them, and is asked for the company if none was found. The user pastes profile links (Supplied picks), confirms the list (can remove or add links), and linkreach reads each profile within the existing page-view caps and stop rules. For each Pick, Claude writes an email subject, body, and Connection note following the Style file; validation runs; the terminal prints every Connection note and an end-of-run summary; the Job, Person, and Pick records are saved. No search, no email lookup, no Gmail yet: an Email finder interface exists with a "none" finder, so every successfully drafted Pick ends `no_email`.

The pipeline is one function the terminal command wraps, so a future dashboard form can call it.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] New Job and Pick storage as described in the spec; a Pick is unique per (Job, Person); a known Person is reused, not duplicated; status history records Pick changes
- [ ] Job description text is sanitized before it reaches Claude; extracted fields are shown for confirmation and can be edited; a missing company prompts the user
- [ ] Supplied picks accept any number of links; links are normalized; the confirm step allows removing and adding links before any profile is read
- [ ] A Style file example (Instructions, Example emails, Example connection notes) is committed; the real Style file at the repo root is gitignored; `init` copies the example only if the real file doesn't exist; `job` refuses to run with a clear message when the Style file is missing
- [ ] The Style file and background block go into the cached system prompt; profile text stays fenced as untrusted data, as today
- [ ] One Claude call per Pick returns subject, body, and note; validation covers subject and body (only `resume_url` allowed as a link, no emails or phone numbers in text, no injection patterns, banned phrases, or HTML, body ≤ 200 words, subject ≤ 80 characters) and the note (≤ configurable `note_max_chars`, default 200); up to 3 attempts
- [ ] An Email finder interface ("given the open profile, return an email or nothing, and why") exists, wired through the command context, with a "none" implementation used by default in this ticket
- [ ] Pick statuses reach `drafted` (only once an email exists, so not in this ticket) or `no_email`; a Pick that fails validation 3 times is left with its validation errors recorded (full `needs_detail` handling comes in 06)
- [ ] Terminal output: each Pick's name, profile link, and Connection note, then a summary (Picks, drafts, failures, page views used)
- [ ] Found emails, subjects, bodies, and notes are never logged and are covered by the redaction filter
- [ ] Tests through the `job` command using the existing fakes (fake browser session, fake Claude, scripted terminal input, no-op sleep) cover: happy path, corrected company, missing company, removed Pick, injection text in a profile, a CAPTCHA stopping the run, page-view cap reached mid-run

## Comments

**2026-11-21:** See 12 (Claude Code backend). The user has no API key, so build this ticket's Claude calls (Job extraction, drafting) on the injectable client object that `Drafter` already uses. Don't call `anthropic.Anthropic` directly. That way 12's `llm_backend: claude_code` works for `job` without changes here.
