# Spec: Local model and web app

Status: ready-for-agent

Supersedes the delivery parts of `.scratch/job-driven-outreach/spec.md` (the terminal commands, Claude drafting, SQLite). That spec's domain rules (Pick lifecycle, Decision-maker roles, ranking tiers, browser safety) still apply unless changed here.

## Problem Statement

linkreach drafts with Claude, through the Anthropic API or Claude Code. I want drafting to run entirely on my own machine with a local model, at no per-token cost and with no Job description, profile data or background leaving my laptop. The terminal flow is also clumsy for this work. Pasting a job description, confirming fields, watching a multi-minute run, then copying Connection notes one by one is better done in a browser page.

Anyone who forks the project should be able to run their own copy with their own accounts, model and profile, with nothing personal committed or shared.

## Solution

linkreach becomes a local web app: a FastAPI server, a React frontend and a Postgres database (in Docker), all on localhost. Every model call goes to a local model served by Ollama. Claude, the Anthropic API and the CLI are removed.

The flow:

1. I paste a Job description and any profile links into a form. The local model extracts company, role, team and location.
2. A confirm screen shows those fields, the company's LinkedIn page and any Persons already emailed for another Job. I edit and click Run.
3. A background Run, one Pick at a time:
   - searches for Found picks to fill the Pick target
   - writes the Angle once per Job
   - for each Pick: reads the profile, finds an email (Apollo, then ContactOut), writes the Email draft, writes the Connection note, and saves the Email draft to Gmail Drafts without review
4. The Run page shows each Pick's progress live.
5. A Connection notes view lists every note with a copy button and a "sent" checkbox.

Drafting follows my Profile file: a short Background, a list of Facts (the only numbers the model may use), Banned phrases, and 2–3 varied example emails and notes. Rules the model could break are checked in code.

## User Stories

### Setup

1. As a job seeker, I want to start Postgres with one `docker compose up`, so that I don't install or configure a database by hand.
2. As a job seeker, I want every per-user setting in a gitignored `.env` (with a committed `.env.example`), so that my fork never commits my details.
3. As a job seeker, I want to choose the local model in `.env`, so that I can switch between models (or use a smaller one on a smaller GPU) without code changes.
4. As a job seeker, I want a Setup page that checks Postgres, Ollama and the model, Gmail, the LinkedIn session, both extension sign-ins, and the Profile file, so that problems are caught before a Run spends page views or credits.
5. As a job seeker, I want a "Log in to LinkedIn" button that opens the Dedicated profile for me to sign in and set up the extensions, so that I never need a terminal.
6. As a job seeker, I want to upload my own Google OAuth client file once and click "Connect Gmail", so that linkreach can create drafts with the compose scope only.
7. As a job seeker, I want the app reachable only from my machine and protected from other websites calling it, so that no page I visit can trigger drafts.

### Profile file

8. As a job seeker, I want one markdown Profile file outside the repo with sections for Background, Facts, Banned phrases, Example emails and Example connection notes, so that every draft follows my pattern.
9. As a job seeker, I want a committed example Profile file to copy, so that I start from a working template.
10. As a job seeker, I want the Setup page to flag a missing section, too few or too many examples, an over-long Background, or a Profile file too large for the model's context, so that I fix it before drafting.

### Starting a Job

11. As a job seeker, I want to paste a Job description and any number of profile links into one form, so that I can start a Job in one step.
12. As a job seeker, I want the extracted company, role, team and location shown for me to edit before anything runs, so that page views and credits are never spent on the wrong company.
13. As a job seeker, I want to be asked for the company when the Job description doesn't name one, so that linkreach never guesses.
14. As a job seeker, I want the company's LinkedIn page shown for confirmation, so that searches target the right company.
15. As a job seeker, I want a Supplied pick already emailed for another Job flagged on the confirm screen (when, which Job), with a checkbox to include them anyway, so that I don't email someone twice by accident.

### The Run

16. As a job seeker, I want the Run to work in the background after I click Run, so that I can leave the page and come back.
17. As a job seeker, I want only one Run at a time, with a clear message if I try to start another, so that the Dedicated profile and GPU aren't fought over.
18. As a job seeker, I want Found picks searched and ranked by the local model, with tier rules, the peer exclusion and the 500-employee CTO/CEO rule enforced in code, so that a small model can't break them.
19. As a job seeker, I want Found picks to go straight to email lookup without an approval stop, so that the Run is hands-off.
20. As a job seeker, I want the Angle written once per Job at the start of the Run and shown on the Run page, so that I can see what every email was based on.
21. As a job seeker, I want each Pick's steps (profile read, email found, Email draft, Connection note, Gmail draft) shown live, so that I know where the Run is.
22. As a job seeker, I want a failure on one Pick to leave the others running, with a "retry from this step" button, so that one bad profile doesn't cost me the Run.
23. As a job seeker, I want a LinkedIn selector failure or CAPTCHA to stop the Run immediately, as today, so that my account stays protected.

### Finding emails

24. As a job seeker, I want Apollo tried first and ContactOut second for each Pick, so that more Picks end up with an email.
25. As a job seeker, I want a separate daily Reveal cap for each finder, set in `.env`, so that neither vendor's credits run out, and a capped finder is skipped for the next.
26. As a job seeker, I want a Pick where both finders fail clearly flagged as `no_email`, with a field to type the email myself, so that I can still email them.
27. As a job seeker, I want a typed-in email to trigger the Email draft and Gmail draft for that Pick, so that a manual email gets the same treatment.

### Drafting

28. As a job seeker, I want the Angle (the Job's core problem and which of my experiences answer it) produced in its own call, so that the email call gets a small, focused prompt.
29. As a job seeker, I want the Email draft and the Connection note written in separate calls, each seeing only its own examples, so that a small model does one task at a time.
30. As a job seeker, I want every number in a subject, body or note checked against my Facts, so that the model never invents metrics.
31. As a job seeker, I want any Banned phrase rejected, so that drafts don't sound generic.
32. As a job seeker, I want the subject, body and Connection note limits enforced (note limit set in `.env`), so that drafts fit where they go.
33. As a job seeker, I want a draft that breaks a rule retried with the exact broken rule named, up to 3 times, then the Pick marked `needs_detail` with no Gmail draft, so that I never get a bad draft in my mailbox.
34. As a job seeker, I want a Connection note drafted even when no email is found, so that LinkedIn is still an option.
35. As a job seeker, I want a "regenerate Angle and redraft all" button on a Job, so that a poor Angle doesn't spoil every draft.
36. As a job seeker, I want an over-budget prompt to fail with a clear error instead of being cut short, so that the model never drafts from half a prompt.
37. As a job seeker, I want scraped profile text still sanitized and fenced as untrusted, so that someone's profile can't steer the model.

### Output and tracking

38. As a job seeker, I want each Email draft saved to Gmail Drafts automatically, with no resume link in it, so that I review it in Gmail and attach my resume myself.
39. As a job seeker, I want a redraft to update the existing Gmail draft rather than add a second one, and to create a new one if I deleted it, so that my Drafts folder stays clean.
40. As a job seeker, I want a Connection notes view (name, profile link, note, character count, copy button, "sent" checkbox), so that I can work through notes quickly.
41. As a job seeker, I want a Picks table per Job and across Jobs, with a status dropdown for the lifecycle, so that I track outreach without a terminal.
42. As a job seeker, I want to add one line of detail to a `needs_detail` Pick and redraft it, so that I can rescue it quickly.

## Implementation Decisions

- **Domain vocabulary** follows `GLOSSARY.md`, with new terms: Angle, Profile file, Facts, Banned phrases, Run. "Style file" is retired in favor of the Profile file.
- **ADRs in force:** 0001 (no automated connection requests; send code deleted), 0002 (fixed pipeline), 0003 (Apollo → ContactOut chain), 0004 (local model via Ollama), 0005 (web app with Postgres).
- **Layout:**
  - the `linkreach/` Python package stays as the backend (domain logic and the FastAPI app)
  - `web/` holds the frontend: Vite + React + TypeScript + TanStack Query + Tailwind CSS
  - `docker-compose.yml` at the root runs Postgres only (named volume, port bound to 127.0.0.1)
  - FastAPI, the browser automation and Gmail OAuth run natively on the host, because they need the visible Chrome window and the local browser
- **Serving:** for everyday use, FastAPI serves the built frontend on one port. In dev, the Vite dev server proxies the API. Both bind to 127.0.0.1. The existing dashboard protections (token header, Host check, CSP) carry over.
- **Database:**
  - SQLAlchemy 2.0 (sync) + psycopg 3 + Alembic migrations, starting fresh with no SQLite import
  - Tables: Person, Job (with the extracted fields, Job description, and the Angle), Pick (as today, minus resume fields, plus which finder produced the email), Run (Job, status, times, error), Run step (Run, Pick, step name, status, detail, times), status history, activity log (page views, Reveals per finder), company caches
- **Config:**
  - `.env` holds the Postgres credentials (shared with docker-compose), Ollama base URL, model name, context size, app port, `NOTE_MAX_CHARS` (default 200), `APOLLO_DAILY_REVEALS`, `CONTACTOUT_DAILY_REVEALS`, the Pick target, the alumni school, and the page-view caps
  - Hard ceilings on caps stay in code
  - The YAML config and `resume_url` are removed
- **Secrets and personal files:**
  - the Gmail refresh token stays in the OS keychain
  - the uploaded Google OAuth client file is kept under `~/.linkreach/`
  - the Profile file lives at `~/.linkreach/profile.md`
  - the Dedicated profile stays at `~/.linkreach/chrome-profile`
  - nothing personal lives in the repo
- **Model client:**
  - `structured_call(system, user, schema)` keeps its role as the single entry point
  - It calls Ollama's native `/api/chat` with a JSON-schema `format`, `think: false`, and `options.num_ctx` from `.env`. The native API is used because Ollama's OpenAI-compatible endpoint can't set the context size per request, and Ollama's default context on GPUs under 24 GB is 4K, which would silently cut prompts off.
  - Temperature is about 0.7 for drafting calls and 0 for extraction and ranking
  - Before each call, code estimates the prompt's tokens conservatively and fails with a clear error if the prompt plus the output reserve exceeds `num_ctx`
  - Default model: `gemma4:12b-it-qat` at an 8K context, with `qwen3.5:9b` as the comparison. If Gemma doesn't stay fully on the GPU at 8K, Qwen becomes the default (decided by issue 13).
  - The `anthropic` dependency, `claude_code.py` and the `llm_backend` option are deleted
- **Model calls (fixed pipeline):**
  1. Extract: Job description → company, role, team, location. Runs on form submit.
  2. Rank: candidate cards → tiers and reasons. Code enforces the rules.
  3. Angle: Job description + Background + Facts → core problem and 1–3 chosen experiences. Once per Job, at Run start, no approval.
  4. Email: Background, Facts, Banned phrases, Example emails, the Angle and trimmed profile data → subject and body. Doesn't see the Job description.
  5. Note: Background, Facts, Banned phrases, Example connection notes, the Angle and trimmed profile data → Connection note.
- **Profile file:** markdown with fixed headings: Background, Facts, Banned phrases, Example emails, Example connection notes.
  - Checks: Background under a word cap; Facts as a bullet list; 2–3 of each example type; the whole file under a token budget that leaves room for the rest of the prompt
  - The parser and checks are shared by the Setup page and the drafting code
  - A committed `profile.example.md` is the template
- **Validation (code-enforced, applies to calls 4 and 5):**
  - every number token in the output must appear in Facts
  - no Banned phrase, ignoring case
  - subject at most 80 characters, body at most 200 words, note at most `NOTE_MAX_CHARS`
  - no links, email addresses or phone numbers in the text; no injection patterns; no HTML
  - Up to 3 attempts, each retry naming the failed rule; after that the Pick becomes `needs_detail`
- **Runs:**
  - a Run is a background thread in the FastAPI process (no Celery or Redis), and starting a second Run returns 409
  - Picks are processed one at a time, in steps: profile read → email found → Email draft → Connection note → Gmail draft
  - each step's state is saved in Postgres; a per-Pick failure is recorded and the Run moves on
  - "retry from this step" re-runs one Pick from a failed step
  - the Run page subscribes over Server-Sent Events
  - LinkedIn selector failures and CAPTCHA/warnings stop the whole Run
- **Email finder:**
  - a chain behind the existing `EmailFinder` protocol: Apollo → ContactOut → `no_email`
  - each finder has its own daily cap; a capped finder is skipped
  - Apollo's panel is reached as Chrome's side panel, using `PW_CHROMIUM_ATTACH_TO_OTHER=1` so it appears among the context's pages, per issue 01's findings
  - finder failures are soft (screenshot, event, next finder)
- **Gmail:**
  - creates a draft, or updates the stored `gmail_draft_id` if it still exists, otherwise creates a new one
  - compose scope only; installed-app loopback OAuth started from the Setup page
- **Removed:** the CLI and its entry point, SQLite, the old dashboard page, `send`/`sync`/`connect_mode` and the connect selectors, the Anthropic and Claude Code backends, the Style file, and `resume_url`.

## Testing Decisions

- **Backend seam:** the FastAPI app driven through its HTTP API (TestClient), with outside dependencies faked:
  - fake browser session and pages, with the Apollo side panel and ContactOut panel modelled on them
  - fake model client returning scripted JSON
  - fake Gmail drafts client recording create/update calls
  - no-op sleep
  - the Run executed inline for tests
- **What tests check:** visible outcomes only:
  - API responses
  - Job, Pick, Run and Run step rows
  - what the fake Gmail received
  - activity-log counts
  - SSE events
- **Database in tests:** a separate `linkreach_test` database in the compose Postgres, with migrations applied once and each test in a rolled-back transaction.
- **Scenarios:**
  - extraction → confirm → Run creates drafts and notes
  - missing company is asked for
  - a duplicate Person is flagged
  - a second Run returns 409
  - Found picks fill to the Pick target and the ranking rules hold
  - Apollo succeeds; Apollo fails and ContactOut succeeds; both fail gives `no_email`, still with a note
  - a finder at its cap is skipped
  - a manual email triggers drafting
  - a made-up number, a Banned phrase and an over-long note each cause a retry, and three failures give `needs_detail` with no Gmail draft
  - an over-budget prompt fails clearly
  - a redraft updates the same Gmail draft, or creates a new one when it was deleted
  - a per-Pick failure doesn't stop the Run, and retry-from-step works
  - a CAPTCHA stops the Run
  - injection text doesn't reach a draft
  - the Setup checks report each failure
  - the Host and token checks reject foreign requests
- **Unit tests kept** for pure helpers: validation rules (number whitelist, Banned phrases), Profile file parsing and checks, sanitization, URL normalization, token estimate.
- **Live model tests** run the real prompts against Ollama and are marked `live_model`, so they only run on request.
- **Frontend:** Vitest + Testing Library for the confirm screen, Run page step rendering and Connection notes view. No end-to-end browser tests.
- **Never called in tests:** real LinkedIn, Apollo, ContactOut and Gmail.

## Out of Scope

- Sending emails or connection requests.
- Reviewing or editing Email drafts in the app before they reach Gmail; Gmail Drafts is the review step.
- Attaching a resume; I attach it in Gmail.
- Dockerizing the app, browser or Ollama.
- Multiple users or authentication beyond the localhost protections.
- Apollo or ContactOut APIs.
- Migrating SQLite data.
- Detecting replies or acceptances automatically.

## Further Notes

- Both vendors' terms forbid automating their extensions (ADR-0003). The per-finder caps and soft failures limit the damage if a vendor reacts.
- On an RTX 4060 (8 GB), `gemma4:12b-it-qat` (7.2 GB) is a tight fit. Issue 13 measures whether it stays fully on the GPU at 8K context.
- `PW_CHROMIUM_ATTACH_TO_OTHER` and the side-panel route are unverified until issue 01. If it fails, Apollo stays an open issue and the chain runs ContactOut alone. The user is told when both finders fail for a Pick either way.
