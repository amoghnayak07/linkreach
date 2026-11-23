# Spec: Job-driven outreach

Status: ready-for-agent

> Partly superseded by `.scratch/local-llm-web/spec.md`: the CLI, Claude drafting, SQLite, the Style file and `resume_url` are replaced. The open issues 08, 09 and 10 are replaced by local-llm-web issues 10 and 05. The domain rules here still apply unless that spec changes them.

## Problem Statement

I'm job hunting, and linkreach today works the wrong way round for me. It starts from a list of companies, collects people in bulk by keyword bucket, drafts LinkedIn notes, and then automates sending connection requests. But I already know which company I want: I've found a specific role. What I need is, for *that* job, the handful of decision-makers worth contacting, their work emails, and a well-written email and connection note for each, in my own voice, that I can review and send myself.

Automated connection requests are also the riskiest thing the tool does to my LinkedIn account, and I'd rather send those by hand. Finding emails today means clicking through Apollo and ContactOut for every person, and writing each email from scratch is slow and inconsistent.

## Solution

A new terminal command, `linkreach job`. I paste a job description (or point it at a file). linkreach works out the company and role and asks me to confirm them. It then asks for any LinkedIn profile links I've already researched, and searches LinkedIn to fill the remaining slots up to the Pick target with decision-makers: hiring managers, team leads and managers, recruiters, and (at small companies) the CTO and CEO. It shows me the Picks with a reason for each, and I approve, remove, or add people.

For each confirmed Pick, linkreach looks up a work email with the Apollo extension (falling back to ContactOut) inside the Dedicated profile. Claude writes an email draft and a connection note following my Style file. Each email draft is saved to my Gmail Drafts folder. Each connection note is printed in the terminal. Everything is stored in the local database. linkreach never sends an email or a connection request: I do that myself, then record it with `linkreach mark`.

The old bulk flow (company and job CSVs, buckets, the alumni pass, batch draft and review) is deleted. The automated `send` path stays in the code, switched off.

## User Stories

### Starting a Job

1. As a job seeker, I want to paste a job description into the terminal, so that I can start outreach for a role without preparing any input files.
2. As a job seeker, I want to pass a job description from a file instead, so that I can reuse a description I've saved, or paste a long one reliably.
3. As a job seeker, I want linkreach to extract the company, role title, team, and location from the job description, so that I don't have to type them.
4. As a job seeker, I want to confirm or correct the extracted company and role before any browsing happens, so that page views and credits are never spent on the wrong company.
5. As a job seeker, I want linkreach to ask me for the company when the job description doesn't name one (for example a staffing-agency posting), so that it never guesses.
6. As a job seeker, I want each run to create a Job record, so that every Pick, draft, and note is tied to the role it was written for.
7. As a job seeker, I want the job description text stored with the Job, so that I can see later what each email was written against.

### Choosing Picks

8. As a job seeker, I want to be asked whether I already have profile links I've researched, so that my own research is used first.
9. As a job seeker, I want to paste any number of profile links, including more than five, so that the Pick target never blocks people I chose deliberately.
10. As a job seeker, I want linkreach to search LinkedIn to fill the remaining slots when I supply fewer links than the Pick target, so that I always end up with a full list.
11. As a job seeker, I want no search at all when my Supplied picks already meet the Pick target, so that page views aren't wasted.
12. As a job seeker, I want the Pick target to default to 5 and be changeable in config and per run, so that I can go wider or narrower for a particular role.
13. As a job seeker, I want Found picks ranked hiring manager first, then team leads and managers in the role's function, then recruiters covering that function or location, so that the people closest to the hiring decision come first.
14. As a job seeker, I want the CTO and CEO considered only at companies with 500 or fewer employees, so that I don't waste outreach on executives at large companies.
15. As a job seeker, I want peers in the same role excluded, so that every Pick is someone who can influence hiring.
16. As a job seeker, I want alumni of my school ranked higher within each tier, so that warmer connections come first.
17. As a job seeker, I want each Pick shown with name, title, tier, and a one-line reason, so that I can judge the list quickly.
18. As a job seeker, I want a Supplied pick whose current company doesn't match the Job's company flagged with a warning but kept, so that I'm alerted to stale profiles without losing my choice.
19. As a job seeker, I want a Pick flagged when that Person was already emailed for another Job (showing when and for which Job), so that I don't accidentally email someone twice.
20. As a job seeker, I want to approve, remove, or add people before any email Reveal happens, so that credits are only spent on people I've confirmed.
21. As a job seeker, I want a Person who's already in the database reused rather than duplicated, so that their history across Jobs stays in one place.

### Finding emails

22. As a job seeker, I want linkreach to find each confirmed Pick's work email with the Apollo extension, so that I don't have to click through it myself.
23. As a job seeker, I want ContactOut tried when Apollo finds nothing or its panel can't be read, so that more Picks end up with an email.
24. As a job seeker, I want a daily cap on Reveals across both extensions (default 15), so that a run can't burn through my credits.
25. As a job seeker, I want Picks that hit the Reveal cap marked as having no email, with the run continuing, so that I still get their connection notes.
26. As a job seeker, I want an extension whose panel has changed to be treated as a soft failure (screenshot, log it, try the other extension), so that a vendor UI change doesn't kill the whole run.
27. As a job seeker, I want a LinkedIn selector failure or a CAPTCHA/warning to still stop the run immediately, so that my LinkedIn account stays protected.
28. As a job seeker, I want found emails checked for a plausible format before they're used, so that a misread panel doesn't produce a draft to a garbage address.

### Drafting

29. As a job seeker, I want a Style file at the repo root (gitignored) with sections for Instructions, Example emails, and Example connection notes, so that every draft sounds like me.
30. As a job seeker, I want the Style file's instructions to govern the email subject as well as the body, so that subjects follow my conventions too.
31. As a job seeker, I want `init` to create the Style file from a committed example when it doesn't exist (and never overwrite it), so that I start from a working template.
32. As a job seeker, I want Claude to write an email draft and a connection note for each confirmed Pick, using the Job, the Pick's profile details, my background, and the Style file, so that each message is specific to the person and role.
33. As a job seeker, I want my resume link included in the email (not attached), so that recipients can find it in one click.
34. As a job seeker, I want email drafts checked like notes are today (no links except my resume, no other emails or phone numbers, no injection patterns, no banned phrases, no HTML), so that a manipulated profile can't put content into my email.
35. As a job seeker, I want hard limits of 200 words for the email body and 80 characters for the subject, with the Style file guiding length within those limits, so that emails stay short.
36. As a job seeker, I want the connection note length limit configurable (default 200 characters; 300 for Premium), so that notes fit my account type.
37. As a job seeker, I want a draft that fails validation 3 times to mark the Pick as needing detail, with no Gmail draft created, so that I never get a bad draft in my mailbox.
38. As a job seeker, I want to add one line of context to a Pick that needs detail and have it redrafted, so that I can rescue it quickly.
39. As a job seeker, I want scraped profile text treated as untrusted (sanitized and fenced off in the prompt, as today), so that text on someone's profile can't steer the model.

### Output

40. As a job seeker, I want each email draft saved to my Gmail Drafts folder, so that I can review, edit, and send it from Gmail myself.
41. As a job seeker, I want linkreach to only ever create drafts and never send, so that nothing goes out without me.
42. As a job seeker, I want no Gmail draft created for a Pick without an email, so that I'm not left with drafts that have no recipient.
43. As a job seeker, I want every connection note printed in the terminal at the end of the run (name, profile link, note), so that I can copy each one into LinkedIn.
44. As a job seeker, I want every email draft and connection note saved in the database, so that I can see them again later.
45. As a job seeker, I want an end-of-run summary (Picks, emails found, drafts created, Picks needing detail, Reveals used, page views used), so that I know what happened.

### Tracking

46. As a job seeker, I want outreach progress tracked per Pick, not per Person, so that someone I emailed for one Job can still be a fresh Pick for another.
47. As a job seeker, I want Picks to move through picked → drafted / no_email / needs_detail → emailed / connected → replied → meeting → referral, with dead reachable from any status, so that my pipeline reads clearly.
48. As a job seeker, I want to record `emailed` and `connected` with `linkreach mark`, so that I can log the sends I made outside linkreach.
49. As a job seeker, I want to list Picks by Job and by status, so that I can see where each role stands.
50. As a job seeker, I want status changes recorded in history, as today, so that I can see when things happened.

### Setup and health

51. As a job seeker, I want `linkreach login` to open the Dedicated profile with no automation so that I can sign in to LinkedIn, install the Apollo and ContactOut extensions, and sign in to them, so that everything linkreach needs persists in one profile.
52. As a job seeker, I want `linkreach gmail-login` to run Google's sign-in for my own OAuth desktop client with only the compose scope, and store the token in the OS keychain, so that linkreach can create drafts without broader mailbox access.
53. As a job seeker, I want `doctor` to check the LinkedIn session, both extension sign-ins, the Gmail token, and the Style file, so that an expired sign-in is caught before a run spends page views or credits.
54. As a job seeker, I want the browser's top-level navigation still limited to LinkedIn while in-page requests may reach Apollo, ContactOut, and extension pages, so that the extensions work without the browser wandering off-site.
55. As a job seeker, I want existing page-view caps, random delays, and stop-on-warning rules applied to every page view in a Job run, so that the new flow is no riskier than the old one.
56. As a job seeker, I want found emails, draft bodies, and the Gmail token kept out of logs, so that logs stay safe to share when debugging.

### Kept and removed

57. As a job seeker, I want the automated `send` path kept in the code but switched off by a `connect_mode: manual` default, so that I can bring it back if a safer route appears.
58. As a job seeker, I want the company and job CSVs, buckets and their shares, the alumni pass, the batch draft and review commands, and the LinkedIn follow-up message removed, so that the tool only has one flow.
59. As a job seeker, I want the old 1,000+ employee rule gone, so that I can target any company I find a role at.

## Implementation Decisions

- **Domain vocabulary** follows the project glossary: Job, Job description, Person, Pick (Supplied / Found), Pick target, Decision-maker roles, Email draft, Connection note, Style file, Email finder, Reveal, Dedicated profile.
- **ADRs in force:**
  - ADR-0001: no automated connection requests; send code kept and switched off.
  - ADR-0002: fixed pipeline, not an agent.
  - ADR-0003: the Email finder drives the Apollo and ContactOut extensions.
- **Fixed pipeline:** read the Job description → confirm the Job → collect Supplied picks → search to fill to the Pick target → rank → confirm Picks → per Pick: read profile, Reveal, draft, validate, save Gmail draft → print notes and summary. Code decides every page view. Claude is called only to (a) extract Job fields from the description, (b) rank and give reasons for candidates, and (c) write the email and note. The pipeline is one function that a future dashboard form can call; the terminal command is a thin wrapper around it.
- **Schema:**
  - New **Job** table: company, role title, team, location, description text, created time.
  - New **Pick** table: Job, Person, supplied or found, tier, reason, status, found email, email subject and body, connection note, validation errors, one-line user detail, Gmail draft id, timestamps. Unique per (Job, Person).
  - **Person** stays unique by normalized profile URL and keeps profile-level facts (name, title, company, alumni flag, profile context).
  - Status history gains a Pick reference.
  - The old person-level status columns stay for the dormant `send` path.
- **Pick status lifecycle:** `picked → drafted | no_email | needs_detail`; `needs_detail → drafted | no_email`; `drafted | no_email → emailed | connected`; `emailed ↔ connected` either order; then `replied → meeting → referral`; `dead` from any status. linkreach sets statuses up to `drafted` / `no_email` / `needs_detail`. The user sets the rest with `mark`.
- **Duplicate guard:** when a Person already has a Pick at `emailed` or later on another Job, the new Pick is flagged at the confirmation step. It is not blocked; the user decides.
- **Job extraction:** Claude returns structured fields from the sanitized description. The user confirms or edits them in the terminal. If no company is found, the user is asked for it. The company's LinkedIn id comes from the existing company-id lookup and cache.
- **Company size:** read from the company page the id lookup already visits, at no extra page view where possible. It only decides whether the CTO and CEO are included (500 or fewer employees).
- **Search:** reuse the existing current-employees people search scoped by company id. Queries come from the Job's role, function, and team plus the Decision-maker role keywords. The search budget per Job is small and fixed, and it counts against the daily page-view cap.
- **Ranking:** Claude ranks sanitized candidate cards into tiers (hiring manager → leads/managers → recruiters → CTO/CEO when allowed), with alumni first within a tier, and returns a one-line reason each. Code enforces the tier rules, the peer exclusion, and the target count.
- **Email finder:** a pluggable step with an interface like "given the open profile page, return an email or nothing, and why". The first implementation drives the Apollo panel injected into the LinkedIn profile page, then ContactOut's. Selectors for both live alongside the LinkedIn selectors as fallback lists. Each Reveal attempt is logged as its own activity event and counted against a daily `reveal_cap` (default 15, ceiling enforced like the other caps). Panel failures produce a screenshot and a `finder_broken` event, and are never fatal.
- **Browser:** the automated launch stops passing Playwright's disable-extensions default. The request filter allows subresource requests to Apollo, ContactOut, and the extension scheme. Top-level navigation stays limited to LinkedIn and fails as today.
- **Style file:** markdown at the repo root, gitignored, with three sections: Instructions (governing subject and body), Example emails, and Example connection notes. A committed example file is the template `init` copies. It replaces the note and follow-up templates in config, which are removed. Its content goes into the cached system prompt next to the background block.
- **Drafting:** one Claude call per Pick returns subject, body, and note. Validation reuses the current rules, extended to subject and body: only `resume_url` may appear as a link; no email addresses or phone numbers in the text; no injection patterns, banned phrases, or HTML. Body is capped at 200 words, subject at 80 characters, and the note at `note_max_chars` (configurable, default 200). There are 3 attempts, then `needs_detail`. Recent openers are still tracked to avoid repetition.
- **Gmail:** a new drafts client interface with a single "create draft (to, subject, body) → draft id" operation. The real implementation uses the Gmail API with the compose scope only, an installed-app OAuth flow for the user's own desktop client, and the refresh token in the OS keychain. `gmail-login` runs the consent flow. The interface is injected through the existing command context.
- **Config:**
  - New: `pick_target`, `reveal_cap`, `note_max_chars`, `connect_mode`.
  - Removed: buckets, `per_company_limit`, `combine_keywords`, the alumni-pass settings, the follow-up template and limits, and CSV inputs.
  - `alumni_school`, `resume_url`, and the background block stay.
- **Commands:**
  - New: `job` (with `--file` and `--picks`) and `gmail-login`.
  - Changed: `mark` and `list` work on Picks, by Job and status; `doctor` adds checks; `init` copies the Style file example; `login` text mentions the extensions.
  - Removed: `collect`, `draft`, `review`.
  - Hidden while `connect_mode` is manual: `send` and `sync`.
- **Logging:** found emails, subjects, bodies, notes, and OAuth tokens are added to the redaction filter, and code doesn't log them in the first place.
- **Dashboard:** its Review and Outbox tabs (and their endpoints) are hidden in this phase, because they depend on the deleted drafting path; the Activity log tab stays. A later phase adds a Job form and removes those tabs for good.

## Testing Decisions

- **One seam:** the `job` command run through the existing command context, with all outside dependencies replaced:
  - fake browser session and pages; Apollo and ContactOut panels modelled as elements on fake profile pages
  - fake Claude client
  - scripted terminal input
  - no-op sleep
  - a new fake Gmail drafts client that records `(to, subject, body)`
- **Good tests check only what's visible from outside:**
  - Job and Pick records and their statuses
  - drafts the fake Gmail received
  - `activity_log` counts for page views and Reveals
  - terminal output

  They don't call internal helpers or check how many times Claude was called, except where a cap is the behavior under test.
- **Scenarios to cover:**
  - Fewer Supplied picks than the target fills with Found picks. As many or more Supplied picks than the target means no search.
  - Ranking tiers, peer exclusion, and the 500-employee CTO/CEO rule.
  - A Pick already emailed for another Job is flagged at confirmation.
  - Removing a Pick at confirmation means it gets no Reveal and no draft.
  - Apollo succeeds. Apollo fails and ContactOut succeeds. Both fail gives `no_email`, with a note but no Gmail draft.
  - The Reveal cap is reached mid-run and the rest become `no_email`.
  - An extension panel is missing: soft failure, the run continues.
  - A LinkedIn selector break or CAPTCHA stops the run.
  - A draft fails validation 3 times: `needs_detail`, no Gmail draft. Adding detail and redrafting succeeds.
  - Injection text in a profile doesn't reach an approved draft.
  - The job description has no company: the user is asked.
  - The user corrects the extracted company.
  - Page-view caps apply across the run.
  - `mark` moves Picks through the new lifecycle and rejects invalid transitions.
  - Redaction hides emails and bodies from logs.
  - `doctor` reports a missing Gmail token, an extension that isn't signed in, and a missing Style file.
- **Unit tests that stay** for pure helpers: validation rules (extended for subject and body), profile URL normalization, sanitization, and config validation.
- **Prior art:**
  - the current collect, draft, send, and dashboard tests and their shared fakes
  - the conftest helpers that build input folders and a temporary database
  - the selector tests that enforce scoping rules (add one making sure extension selectors are scoped to the extension's panel)
- **Real Gmail, LinkedIn, Apollo, and ContactOut** are never called in tests. Extension selectors are verified live through `doctor`, like the LinkedIn ones.

## Out of Scope

- Sending emails or connection requests. The `send` path stays switched off.
- The dashboard Job form and live progress view (next phase), and deleting the dashboard's Review and Outbox code (this phase only hides those tabs).
- Detecting sends, replies, or acceptances automatically from Gmail or LinkedIn. Progress is marked by hand for now.
- Searching for companies or roles. The user always brings the job.
- The ContactOut or Apollo APIs, and a manual-reveal Email finder (the pluggable interface allows them later).
- Attaching a resume file.
- Follow-up emails or sequences.
- Multiple user accounts or Style files per Job.

## Further Notes

- Both vendors' terms forbid automating their extensions (Apollo §3(f)(iv) and §3(g)(ii)(2); ContactOut §6.4 in spirit), and an account ban is a known, accepted risk (ADR-0003). The Reveal cap and soft-failure handling keep the damage small if a vendor reacts.
- The extensions' panel markup hasn't been inspected live yet. The first implementation task should open a real profile in the Dedicated profile with both extensions signed in, record working selectors, and confirm that extensions load under the changed launch settings, before building on them.
- The 200-character default for connection notes reflects my understanding of LinkedIn's free-account limit. Check it against the user's account.
- Sign-ins (LinkedIn, Apollo, ContactOut) persist in the Dedicated profile between runs. Gmail's refresh token persists in the keychain. `doctor` catches any that have expired.
