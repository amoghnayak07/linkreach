# 07: Run engine and Run page

**What to build:** Clicking Run starts a background Run for the Job. It writes the Angle, then for each Supplied pick reads the profile and drafts the Connection note. The Run page shows each step live. This is the tracer for Runs: email finding, Email drafts and Found picks plug in later.

**Blocked by:** 04, 05, 06

**Status:** ready-for-agent

- [ ] A Run is a background thread in the FastAPI process; starting one while another runs returns 409 with a clear message
- [ ] Run and Run step rows are saved per step: profile read, email found, Email draft, Connection note, Gmail draft. Steps not built yet are recorded as skipped.
- [ ] Angle call: Job description + Background + Facts → core problem and 1–3 chosen experiences; stored on the Job, no approval
- [ ] Note call: Background, Facts, Banned phrases, Example connection notes, Angle and trimmed, sanitized, fenced profile data → Connection note
- [ ] Code checks on the note:
  - numbers only from Facts
  - no Banned phrases
  - at most `NOTE_MAX_CHARS`
  - no links, emails, phones, injection patterns or HTML
  - up to 3 attempts naming the failed rule, then `needs_detail`
- [ ] Per-Pick failure is recorded and the Run continues; LinkedIn selector failure or CAPTCHA stops the Run; page-view caps apply
- [ ] SSE endpoint streams step changes; the Run page shows the Angle (read-only), one row per Pick with step statuses, and a short log
- [ ] "Retry from this step" on a failed Pick step
- [ ] Tests: happy path; second Run 409; made-up number and Banned phrase retries; 3 failures → `needs_detail`; per-Pick failure continues; CAPTCHA stops; injection text doesn't reach a note; SSE events; retry from step
