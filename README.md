# linkreach

A Python CLI for outreach about one job at a time. You paste a job description; linkreach finds the decision-makers worth contacting at that company (starting from any LinkedIn profiles you've already researched), and Claude writes an email draft and a connection note for each one in your own voice. Email drafts land in your Gmail Drafts folder and connection notes are printed in the terminal. linkreach never sends anything: you send each email and connection request yourself, then record it with `linkreach mark`.

> **Read this first.** LinkedIn's User Agreement prohibits automated tools that access the site. linkreach reads profiles and search results through Playwright; the caps, delays, and stop-on-warning rules here lower the risk, but they don't remove it. Your account can still be restricted.

## Required before first use

1. **Full-disk encryption on.** FileVault (macOS) or BitLocker / Device Encryption (Windows). The DB holds names, notes, and your LinkedIn session cookies live in the Chrome profile.
2. **With an API key (`llm_backend: api`): a monthly spend limit in the Anthropic Console** (Settings → Limits). The SDK retries on errors, so set a cap you're comfortable losing. With `llm_backend: claude_code` there's no API bill; calls use your Claude plan (see [Reaching Claude](#reaching-claude-api-key-or-claude-code)).
3. Python 3.11+ and Google Chrome installed.

## Setup

macOS / Linux:

```bash
cd linkreach
python3 -m venv .venv && source .venv/bin/activate
pip install --require-hashes -r requirements.txt
pip install --no-deps -e .
```

Windows (PowerShell):

```powershell
cd linkreach
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements.txt
pip install --no-deps -e .
```

`requirements.txt` was locked on Windows with Python 3.11. On macOS, run `make lock` (needs `pip install pip-tools`) once to regenerate both lock files for your platform. Always lock with Python 3.11, the oldest version linkreach supports: a lock built on 3.12 or newer leaves out packages that only older Pythons need (such as `backports-tarfile`), so `pip install --require-hashes` and `make check` then fail on 3.11. A lock built on 3.11 works on newer versions too.

Then, in the folder where you want to keep your input files:

```bash
linkreach init        # copies config.yaml and style.md here (never overwrites)
linkreach set-key     # llm_backend: api only. Stores ANTHROPIC_API_KEY in the OS keychain (hidden input)
linkreach gmail-login --client-file client.json   # lets `job` save drafts to Gmail; see "Gmail drafts" below
```

Edit `config.yaml`: set `resume_url`, check your background block, and set `doctor_profile_url` to a public profile with an About section. Edit `style.md` (see [Your Style file](#outreach-for-one-job-linkreach-job)). Those two files are all the input folder holds.

**Upgrading from the old bulk flow.** `collect`, `draft`, and `review`, the `companies.csv` and `jobs.csv` inputs, buckets, the alumni pass, and the LinkedIn follow-up message are gone. linkreach ignores leftover CSV files, but refuses to start while `config.yaml` still has a removed setting (`buckets`, `per_company_limit`, `combine_keywords`, `alumni_angle`, `exclude_title_keywords`, `templates`, `followup_max_words`), and names each one so you can delete it.

### Reaching Claude: API key or Claude Code

Every Claude call linkreach makes (Job extraction and drafting) goes through one client, picked by `llm_backend` in `config.yaml`:

| `llm_backend` | How it reaches Claude | Needs |
| --- | --- | --- |
| `api` (default) | The Anthropic API through the Python SDK | An API key (`linkreach set-key` or `.env`) |
| `claude_code` | The Claude Code CLI on this computer, run as `claude -p` and signed in with your own Claude account | Claude Code installed, and signed in once (run `claude`, then `/login`) |

API key lookup order (`api` only): OS keychain → `ANTHROPIC_API_KEY` environment variable → `.env` in the input folder → `~/.linkreach/.env`. See `.env.example`. With `claude_code`, linkreach never looks for or asks for a key.

**`claude_code` details.**
- Each call runs `claude -p` as a plain text-in, JSON-out model call, never as an agent: all tools off (`--tools ""`), no MCP servers (`--strict-mcp-config`), no user/project/local settings (`--setting-sources ""`), no skills or slash commands, no saved session, and a fresh empty temp folder as the working directory, so no `CLAUDE.md` is loaded. The system prompt goes in a temp file and your profile data on stdin, so neither shows up in process listings.
- `claude_code_path` (default `claude`, found on PATH) can point at the executable directly, for example `C:/Users/you/.local/bin/claude.exe` on a Windows install outside PATH. `claude_code_timeout_seconds` (default 120) caps one call.
- `use_refusal_fallbacks` and prompt caching are API-only and are skipped.
- Failures show a plain message: not signed in, usage limit reached, timeout, or a non-zero exit.
- `linkreach doctor` checks that `claude` is found and makes one tiny no-tools call to confirm you're signed in.

**On a Claude Team or Enterprise seat** (for example, if you have no API key): calls count against your seat's usage limits like any other Claude Code use, and a `job` run makes a few calls per Pick (up to 3 drafting attempts each). Check that your organization allows scripted and personal use of Claude Code before you turn this on.

### The Chrome profile

linkreach uses its own Chrome profile at `~/.linkreach/chrome-profile`, used for LinkedIn and nothing else. It refuses to start if `chrome_profile_dir` points at your everyday Chrome profile or any profile inside it.

To see where your everyday profile lives (so you know what *not* to use), open `chrome://version` in Chrome and read **Profile Path**. The defaults are:

| OS | Default Chrome user-data folder (refused) |
| --- | --- |
| macOS | `~/Library/Application Support/Google/Chrome/` (profiles: `Default`, `Profile 1`, …) |
| Windows | `%LOCALAPPDATA%\Google\Chrome\User Data\` (profiles: `Default`, `Profile 1`, …) |
| Linux | `~/.config/google-chrome/` |

Sign in once:

```bash
linkreach login       # opens plain Chrome on the dedicated profile; sign in, then close the window
linkreach doctor      # checks selectors, login, Claude access (API key or Claude Code), caps, DB integrity
```

linkreach never asks for, reads, or stores your LinkedIn password. `login` opens ordinary Chrome (no automation, no domain filter) on the dedicated profile, because LinkedIn's sign-in loads security-check scripts from other domains and hangs under the filter. Sign in, wait for your feed, then close that window; `login` then checks the session under the normal filtered browser. Every other command runs with the domain allowlist on.

## Outreach for one job: `linkreach job`

You've found a role you want. `linkreach job` takes its job description and the LinkedIn profiles you've already researched, and writes an email draft and a connection note for each person (a Pick). It never sends anything.

```bash
linkreach job                  # paste the job description, then type END on its own line
linkreach job --file jd.txt    # or read it from a file
linkreach job --picks 3        # aim for 3 Picks this time (default: pick_target in config.yaml, 5)
```

1. Claude reads the company, role, team, and location from the description. Press Enter to keep each value or type a correction. If the description doesn't name a company (for example a staffing-agency post), you're asked for it; linkreach never guesses.
2. Paste profile links, one or more per line, then an empty line. Links are normalized (`linkedin.com/in/Jane-Doe?trk=…` becomes `https://www.linkedin.com/in/jane-doe/`), and anything that isn't a LinkedIn profile is skipped. Any number of links is fine; they're never cut to fit the Pick target.
3. If you gave fewer links than the Pick target, linkreach searches the company's current employees to fill the rest (Found picks). First confirm the company's LinkedIn page: it offers the page you used last time for that company, or a guess from the name. Press Enter to keep it, paste the right link, or type `-` to skip the search. The search costs one page view to read the company's id and size (cached for 90 days) plus at most 4 searches, all under the daily cap. People already in the database are skipped without opening their profiles. Claude sorts the rest into tiers: likely hiring manager for the role's team, then team leads and managers in the function, then recruiters, then the CTO and CEO, who are only considered at companies with 500 or fewer employees (unknown size counts as large). Code enforces the tier order, puts alumni of `alumni_school` first within a tier, and drops peers in the same role. If you gave enough links, no search runs.
4. Confirm the list: your links first, then Found picks with their tier and a one-line reason. Enter starts, `-2` removes Pick 2, pasting a link adds it, `q` quits without saving. No profile is opened and nothing is saved before you confirm.
5. linkreach reads each profile (same page-view caps, delays, and stop-on-CAPTCHA rules as every other command), then Claude writes the email subject, body, and connection note in one call. Code checks them (below) and retries up to 3 times with the reasons. If a link you pasted doesn't show the Job's company in its headline or top card, you get a warning, and the Pick is kept.
6. A Pick with an email gets its email draft saved to your Gmail Drafts folder and moves to `drafted`. A Pick without an email gets no Gmail draft and ends `no_email`. A Pick whose draft fails validation 3 times ends `needs_detail`, with no Gmail draft.
7. The terminal prints every Pick's name, profile link, and connection note (or why there isn't one), then a summary: Picks, drafts, Gmail drafts, needs detail, failures, emails found, page views used.

`job` refuses to start without your Style file or a Gmail sign-in (see [Gmail drafts](#gmail-drafts)). The Job, each Person, and each Pick (with its email, subject, body, note, and Gmail draft id) are saved in the database. A Person already in the database is reused, so their history across Jobs stays together. Email lookup isn't built yet (tickets 08 and 09), so for now every drafted Pick ends `no_email`.

**Rescuing a Pick: `linkreach redraft`.** A Pick that ends `needs_detail` is listed in the summary with the reasons. Run `linkreach redraft` (or `linkreach redraft --job 3` for one Job): it shows each `needs_detail` Pick with its reasons and asks for one line of context, for example "spoke at Grace Hopper about AI hiring". Claude redrafts from what's already saved, with no browser and no new email lookup. A draft that passes goes through the same path as `job` (Gmail draft and `drafted` with an email, `no_email` without) and its connection note is printed; one that fails again stays `needs_detail` with the new reasons. Press Enter to skip a Pick, or `q` to stop. Your line is cleaned like profile text and fenced in the prompt; a line with a link, an email address, or instruction-like words is refused, and you're asked again.

If Gmail fails for one Pick (a network error, say), the run carries on. That Pick's draft and note are saved and printed, its status doesn't move, and the failure is logged without any content. `linkreach redraft` retries the Gmail draft first, without asking anything.

### Gmail drafts

linkreach saves each email draft to your Gmail Drafts folder. You read, edit, and send it from Gmail yourself. It asks Google only for the `gmail.compose` scope, which allows creating drafts, and linkreach has no code that sends mail. It uses your own Google Cloud OAuth client, so no third party holds your mailbox access.

One-time setup:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project (or pick one) and enable the **Gmail API** (APIs & Services → Library → Gmail API → Enable).
2. Set up the OAuth consent screen (APIs & Services → OAuth consent screen, or "Google Auth Platform"): user type **External**, any app name, your email as support and developer contact. Under **Data access** (scopes), add `https://www.googleapis.com/auth/gmail.compose`. Under **Audience**, add your own Gmail address as a test user. You can leave the app in Testing mode.
3. Create a client: APIs & Services → Credentials → Create credentials → OAuth client ID → Application type **Desktop app**. Download its JSON file and keep it outside this repo.
4. Run:

   ```bash
   linkreach gmail-login --client-file ~/Downloads/client_secret_XXXX.json
   ```

   Your browser opens Google's consent page. Sign in, allow "create drafts", and the tab says you're done. linkreach catches the answer on a one-time `127.0.0.1` port (with PKCE), checks that only the compose scope was granted, and stores the refresh token, with the client id and secret, in the OS keychain under service `linkreach`. The token is never written to disk, printed, or logged.

While the app is in Testing mode, Google expires the sign-in after 7 days. `job` then says the Gmail sign-in expired; run `gmail-login` again. To revoke access, remove the app at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).

The Gmail client uses only Python's standard library (HTTPS to `oauth2.googleapis.com` and `gmail.googleapis.com`), so no dependency was added.

**Tracking progress.** linkreach never sends, so you record what you did yourself, per Pick:

```bash
linkreach list                       # every Pick: id, Job, person, status, whether an email was found
linkreach list --job 3 --status no_email
linkreach mark 42 emailed            # you sent the email draft
linkreach mark 42 connected          # you sent the connection note (either order)
linkreach mark 42 replied            # then meeting, then referral; dead works from any status
```

A Pick moves `picked → drafted | no_email | needs_detail` (linkreach sets these; `mark` refuses them), then `drafted | no_email → emailed | connected` in either order, then `replied → meeting → referral`. `mark` rejects any other move and says where the Pick can go. Every change is recorded in the status history. If someone you're adding to a new Job was already emailed (or got further) for another Job, the confirmation step flags it, for example "already emailed on 2026-11-20 for Job #3 Product Manager II at Microsoft". The Pick is kept unless you remove it.

**Your Style file.** `style.md`, next to `config.yaml`, is how every email and note should sound. It has three sections: Instructions (they govern the subject, body, and note), Example emails, and Example connection notes. `linkreach init` creates it from `linkreach/examples/style.example.md` if it doesn't exist and never overwrites it. It's gitignored. `job` refuses to run without it. It goes into the cached system prompt next to your `background` block.

**Draft checks.** Subject at most 80 characters and one line; body at most 200 words and must contain your `resume_url`; connection note at most `note_max_chars` (default 200, the free-account limit; set 300 if you have Premium). Only `resume_url` may appear as a link, and only in the body. No email addresses, phone numbers, instruction-like text, banned phrases, or HTML anywhere. Found emails, subjects, bodies, and notes are never logged, and the log redaction filter scrubs them (and any email address) as a second line of defense.

## Daily use

```bash
linkreach doctor              # before a run: selectors, LinkedIn sign-in, Claude access, caps, DB
linkreach job                 # one job: paste the description, confirm Picks, get drafts and notes
linkreach redraft             # add context to needs_detail Picks and redraft; retry failed Gmail drafts
linkreach list --job 3 --status no_email
linkreach mark 42 emailed     # Pick 42: emailed | connected | replied | meeting | referral | dead
linkreach dashboard           # http://127.0.0.1:8765, opens in your browser
linkreach export              # people to linkreach_export.csv
linkreach purge --older-than 180d
```

### The dashboard

`linkreach dashboard` shows the People, Companies, Insights, and Activity log tabs. The strip under the header shows what the tool is doing right now (for example "job running · last: view · Jane Doe · 3s ago"), and a red banner appears when the last run stopped on a CAPTCHA or warning. The page refreshes every 4 seconds, and the Activity log tab has a Live toggle.

The old Review, Outbox, and Follow-ups tabs are gone, along with their endpoints: they belonged to the deleted `draft` / `review` flow. A Job form for the dashboard is planned; until then, Jobs and Picks live in the terminal (`job`, `list`, `mark`).

## The switched-off send path

> **Sending is switched off by default** (`docs/adr/0001-no-automated-connection-requests.md`). With `connect_mode: manual`, the default, `send` and `sync` are hidden from `--help` and refuse to run (exit code 7). You send connection requests yourself on LinkedIn. The code stays in place, untouched by the Job flow, in case a safer route appears.

With `connect_mode: automated`, `linkreach send` works through people with status `approved` in the person-level table (nothing in the current flow approves anyone), re-validates each connection note, and fills LinkedIn's connect dialog: Enter sends, `s` skips, `q` quits. `linkreach sync` marks 1st-degree connections `accepted`. The rollout rule it was built for: run `send` by hand for three weeks, and only switch to `send --auto` once acceptance holds at 25% or higher across 30+ requests older than 7 days (the brake enforces this).

### Scheduling `send --auto`

Only applies with `connect_mode: automated`. With the default, `manual`, a scheduled `send --auto` exits with code 7 and sends nothing.

`send --auto` runs `doctor` first and aborts on any failure. It only sends inside `auto_window` (default weekdays 9:00 to 18:00 local) and refuses to run while the brake is tripped unless you pass `--override-brake`. One run per weekday is enough: each run sends up to the daily cap.

**macOS / Linux (cron):** `crontab -e`, then:

```cron
# 10:15 on weekdays. Chrome needs your logged-in desktop session, so use your user crontab.
15 10 * * 1-5 cd /path/to/inputs && /path/to/linkreach/.venv/bin/linkreach send --auto >> ~/.linkreach/logs/cron.out 2>&1
```

On macOS, give `cron` Full Disk Access (System Settings → Privacy & Security) if the job can't read `~/.linkreach`.

**Windows (Task Scheduler):** run once in PowerShell:

```powershell
schtasks /Create /TN "linkreach send" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 10:15 /TR "\"C:\path\to\linkreach\.venv\Scripts\linkreach.exe\" --inputs \"C:\path\to\inputs\" send --auto"
```

Keep the default "Run only when user is logged on" so Chrome can open a window.

## Safety rules and where they live

| Rule | Where |
| --- | --- |
| 40 page views/day, 20 requests/day, 80 per rolling 7 days. Config can lower these, never raise them. | `config.py` (ceilings), `safety.py` (counts from `activity_log`) |
| Random 8 to 25 s between page loads | `linkedin.py: LinkedIn.visit` |
| CAPTCHA, security check, "unusual activity", restriction page: log it, stop at once, no retry | `linkedin.py: detect_stop`, phrases and selectors in `selectors.py` |
| linkreach never sends email: Gmail access is the `gmail.compose` scope, and the code only creates drafts | `gmail.py` |
| Automated connection requests are off unless `connect_mode: automated`; even then only approved notes are sent, each re-validated before typing | `commands/common.py: refuse_if_manual`, `commands/send.py` |
| Acceptance brake: 30+ requests older than 7 days below 25% disables `--auto` | `safety.py: brake_status` |
| Send fails or Pending doesn't appear → `failed`, move on | `commands/send.py` |
| Selectors fail on 3 profiles in a row → stop, screenshot, `selector_broken` | `commands/common.py: FailStreak` |
| No duplicate sends after a crash: `send_attempted_at` is committed before the click | `commands/send.py` |
| One Person per profile: `profile_url` is unique and normalized, so a Person is reused across Jobs; search results already in the database are skipped before any profile view, and a Pick already emailed for another Job is flagged at confirmation | `db.py`, `jobsearch.py`, `jobflow.py: contact_flags` |

## Security notes

**Browser isolation.** Dedicated profile only. Top-level navigation is allowed to `linkedin.com` and `licdn.com` (plus subdomains); anything else aborts the run, and third-party subresources are blocked. The code never calls `page.evaluate`.

**Prompt injection.** Scraped profile text and the pasted job description are stripped of HTML, control, and zero-width characters and capped. Profile fields that contain instruction-like text, URLs, or emails are dropped from the prompt. The rest goes inside `<profile_data>` and `<job_description>` tags with a system prompt saying it's untrusted data. Every draft is checked in code (`validate.py`): no URL other than `resume_url` (and that only in the body), no email addresses, phone numbers, instruction patterns ("ignore", "system prompt", "as an AI"), banned phrases, HTML, or length overruns. A draft that fails 3 times is never saved as a draft or sent to Gmail.

**Dashboard.** Bound to `127.0.0.1:8765`. Requests with a Host header other than `127.0.0.1:8765` or `localhost:8765` get 403 (DNS rebinding). A random 32-byte token is created at each start and passed in the URL fragment, which browsers never send to the server. Every `/api` call must carry it in `X-Linkreach-Token`. No CORS headers. State changes are POST only. All data renders through `textContent`. CSP is `default-src 'self'` plus a per-launch nonce for the page's single inline `<script>` and `<style>` block (the spec asks for both a one-file page and `default-src 'self'`; the nonce lets both hold without `unsafe-inline`).

**Secrets.** API key from the keychain (or no key at all with `llm_backend: claude_code`, which uses Claude Code's own sign-in). The Gmail refresh token lives only in the keychain too, and access tokens only in memory. Logs are JSON, rotate at 10 MB × 5, and pass through a redaction filter that scrubs API keys, cookies, the dashboard token, email addresses, and any subject/body/note/message field. Code never logs message bodies in the first place.

**Data at rest.** Everything private lives in `~/.linkreach/` (override with `LINKREACH_HOME`): folder 700, files 600. On Windows, `chmod` only toggles read-only. The folder sits inside your user profile, which Windows already restricts to your account, and BitLocker covers the rest.

**Dependencies.** Exact pins with hashes (`pip-compile --generate-hashes`). `make check` (or `python scripts/check.py` on Windows) runs `pip-audit --strict` and `bandit`, failing on any known vulnerability or high-severity finding. Runtime dependencies are only the allowed list. Dev-only: `pytest`, `httpx` (FastAPI's test client needs it), `pip-audit`, `bandit`, and `pip-tools` (to build the lock file).

## When LinkedIn changes its UI

`doctor` fails, or a run stops with `selector_broken` and a screenshot in `~/.linkreach/logs/screenshots/`. Open `linkreach/selectors.py`, where every selector is a list of fallbacks. Inspect the element in the dedicated Chrome profile, put the new selector first, and rerun `linkreach doctor`.

LinkedIn's 2026 UI scrambles CSS class names on every build, so don't use classes. The current selectors (checked live on 2026-11-21) use:

- **Profile cards** whose id ends in their name: `[id$='Topcard']`, `[id$='About']`, `[id$='Featured']`, `[id$='SalesInsightsOrHighlights']` ("You both studied at…", used for the alumni check). Experience and Education only load after scrolling and usually aren't read.
- **Connect** as the invite link carrying the profile's own vanity name (`a[href*='custom-invite/?vanityName=<slug>']`), then other top-card-scoped controls. Every profile also lists other people with their own "Invite X to connect" buttons, so connect selectors must never be page-wide (a test enforces this).
- **Send** only as `aria-label='Send invitation'` or exact text `Send`. The first dialog also has "Send without a note", so never match a bare "Send" substring (a test enforces this too).
- **Search results** where the name is the `/in/` link directly inside a `<p>`, the headline is the next `<p>`, and the "Current: …" snippet is preferred as the title. LinkedIn serves at least two result layouts, and both work.

Not yet seen live, so treat them as unverified until the first real `send`: the Pending state after an invite, and Connect inside the More menu (profiles where Follow is the main button).

## Exit codes

`0` ok (cap reached counts as ok) · `2` input files invalid · `3` stopped by a CAPTCHA, warning, or off-domain navigation · `5` selectors broken · `6` doctor failed · `7` `--auto` refused (window or brake) · `130` interrupted.

## Tests

```bash
pip install --require-hashes -r requirements-dev.txt
python -m pytest            # make test
python scripts/check.py     # make check
python scripts/demo_dashboard.py   # dashboard with fake data at http://127.0.0.1:8765/#token=demo-token-not-secret
python scripts/demo_cli.py         # terminal walkthrough of `job`, `redraft`, `mark`, `list` with fake LinkedIn, Claude, and Gmail
```

The tests use a fake browser (`tests/fakes.py`), a fake Claude client (plus a fake process runner for the Claude Code backend), and a fake Gmail, so they never touch LinkedIn, the API, Gmail, or the real `claude` CLI. They cover the Job flow end to end (Supplied and Found picks, ranking rules, Gmail drafts, needs detail and redraft), caps, CAPTCHA stops, the Pick lifecycle, injection, the dormant send path (caps, brake, crash-resume), dashboard hardening, and log redaction.

## Where this goes beyond the spec

- **Extra `people` columns:** `validation_errors`, `send_attempted_at` (duplicate-send guard), `updated_at`. Person-level columns from the old bulk flow (`bucket`, `followup_draft`, `user_detail`) stay in the schema so existing databases keep working; nothing writes them now.
- **Extra commands:** `init`, `login`, `set-key`, `gmail-login`, `redraft`, `list`.
- **Searches:** LinkedIn's People tab now ignores `?keywords=`, so `job` reads the company's numeric id (and size) from that tab (one page view, then cached in the database for 90 days) and searches `/search/results/people/?keywords=…&currentCompany=["<id>"]`, which is current employees only.
- **Model:** `claude-sonnet-5-5`, with server-side refusal fallbacks on (`use_refusal_fallbacks`, API backend only). Prompt caching (API backend only) covers the system prompt, background block, Style file, and job description. Very short configs may fall under the minimum cacheable size, in which case caching quietly doesn't apply.
