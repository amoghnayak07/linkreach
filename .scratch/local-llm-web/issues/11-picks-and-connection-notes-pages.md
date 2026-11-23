# 11: Picks and Connection notes pages

**What to build:** The tracking pages that replace `list`, `mark` and `redraft`, plus the Connection notes view and the "regenerate Angle and redraft all" button.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Jobs list → Job detail with its Picks table; an all-Picks table filterable by Job and status
- [ ] Status dropdown enforcing the lifecycle from the job-driven-outreach spec, with status history recorded
- [ ] Connection notes view: name, profile link, note, character count against `NOTE_MAX_CHARS`, copy button, and a "sent" checkbox that marks the Pick `connected`
- [ ] `needs_detail` Pick: a one-line detail box and a Redraft button, which re-runs the failed drafting steps and updates the Gmail draft
- [ ] "Regenerate Angle and redraft all" on a Job: new Angle, then redraft every Pick's Email draft and note, updating Gmail drafts. It is a Run, so the 409 rule applies.
- [ ] Tests: invalid transition rejected; sent checkbox marks `connected`; redraft with detail; regenerate Angle updates drafts; Vitest for the Connection notes view
