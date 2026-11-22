# linkreach

A Python CLI that finds recruiters and product leaders at established companies, drafts a connection note and a follow-up for each with the Claude API, sends the requests you approve on LinkedIn through Playwright, and tracks results in a local dashboard.

> **Read this first.** LinkedIn's User Agreement prohibits automated tools that access the site or send invitations. The caps, delays, brake, and stop-on-warning rules here lower the risk; they don't remove it. Your account can still be restricted. Follow the rollout plan and keep `send` manual until the numbers say otherwise.

## Required before first use

1. **Full-disk encryption on.** FileVault (macOS) or BitLocker / Device Encryption (Windows). The DB holds names, notes, and your LinkedIn session cookies live in the Chrome profile.
2. **With an API key (`llm_backend: api`): a monthly spend limit in the Anthropic Console** (Settings → Limits). `draft` makes up to 5 parallel calls and retries on errors, so set a cap you're comfortable losing. With `llm_backend: claude_code` there's no API bill; calls use your Claude plan (see [Reaching Claude](#reaching-claude-api-key-or-claude-code)).
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
linkreach init        # copies config.yaml, style.md, companies.csv, jobs.csv here (never overwrites)
linkreach set-key     # llm_backend: api only. Stores ANTHROPIC_API_KEY in the OS keychain (hidden input)
```

Edit `config.yaml`: set `resume_url`, check your background block, and set `doctor_profile_url` to a public profile with an About section. Edit `companies.csv` (companies with 1,000+ employees only). `jobs.csv` is optional.

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
- `draft` runs at most 2 calls at a time (each one starts a process), instead of 5.
- `use_refusal_fallbacks` and prompt caching are API-only and are skipped.
- Failures show a plain message: not signed in, usage limit reached, timeout, or a non-zero exit.
- `linkreach doctor` checks that `claude` is found and makes one tiny no-tools call to confirm you're signed in.

**On a Claude Team or Enterprise seat** (for example, if you have no API key): calls count against your seat's usage limits like any other Claude Code use, and a `draft` run with many people uses a fair amount. Check that your organization allows scripted and personal use of Claude Code before you turn this on.

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

## Rollout plan

1. **Weeks 1 to 3:** run `send` without `--auto`. The tool fills the connect dialog and waits for you to press Enter before it clicks Send.
2. **Week 1:** keep `companies.csv` to two or three companies until the selectors work end to end.
3. **Week 4 onward:** switch to `send --auto` if acceptance holds at 25% or higher across 30+ requests older than 7 days. The brake enforces this.

## Outreach for one job: `linkreach job`

You've found a role you want. `linkreach job` takes its job description and the LinkedIn profiles you've already researched, and writes an email draft and a connection note for each person (a Pick). It never sends anything.

```bash
linkreach job                  # paste the job description, then type END on its own line
linkreach job --file jd.txt    # or read it from a file
```

1. Claude reads the company, role, team, and location from the description. Press Enter to keep each value or type a correction. If the description doesn't name a company (for example a staffing-agency post), you're asked for it; linkreach never guesses.
2. Paste profile links, one or more per line, then an empty line. Links are normalized (`linkedin.com/in/Jane-Doe?trk=…` becomes `https://www.linkedin.com/in/jane-doe/`), and anything that isn't a LinkedIn profile is skipped. Any number of links is fine.
3. Confirm the list: Enter starts, `-2` removes link 2, pasting a link adds it, `q` quits without saving. No profile is opened before you confirm.
4. linkreach reads each profile (same page-view caps, delays, and stop-on-CAPTCHA rules as every other command), then Claude writes the email subject, body, and connection note in one call. Code checks them (below) and retries up to 3 times with the reasons.
5. The terminal prints every Pick's name, profile link, and connection note, then a summary: Picks, drafts, failures, emails found, page views used.

The Job, each Person, and each Pick (with its subject, body, and note) are saved in the database. A Person already in the database is reused, so their history across Jobs stays together. Email lookup and Gmail drafts aren't built yet, so every drafted Pick currently ends `no_email`; a Pick whose draft fails validation 3 times keeps its status `picked` with the reasons stored.

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

> **Sending is switched off by default.** With `connect_mode: manual` (the default in `config.yaml`), linkreach doesn't send connection requests: `send` and `sync` are hidden from `--help` and refuse to run. You send requests yourself on LinkedIn. Set `connect_mode: automated` to bring the old automated path back (see `docs/adr/0001-no-automated-connection-requests.md`); the `send` and `sync` lines below and the rollout plan above only apply then.

```bash
linkreach collect --dry-run   # see the planned searches; opens nothing
linkreach collect             # alumni pass, then each bucket, companies in priority order
linkreach draft               # Claude writes a note + follow-up for each `collected` person
linkreach review              # a approve · e edit in $EDITOR · d add detail + redraft · s skip · q quit
linkreach send                # connect_mode: automated only. Shows each note, Enter sends, s skips, q quits
linkreach sync                # connect_mode: automated only. Every few days: marks 1st-degree connections `accepted`
linkreach dashboard           # http://127.0.0.1:8765, opens in your browser
linkreach mark 42 emailed     # Pick 42: emailed | connected | replied | meeting | referral | dead
linkreach list --job 3 --status no_email
linkreach export              # linkreach_export.csv
linkreach purge --older-than 180d
```

### Approving in the dashboard

`linkreach dashboard` opens on the **Review** tab, a point-and-click version of `linkreach review`:

- Each card shows the person, the profile details the draft used, the connection note with a character count, and the follow-up (click to expand).
- **Approve** (`a`) re-validates the stored draft on the server first. A draft that fails moves to Needs detail with the reason shown. **Decline** (`x`) marks the person `skipped`. Both show an Undo for 6 seconds.
- **Edit** (`e`) opens the note and follow-up inline, with live counters and live validation as you type. **Add detail & redraft** (`r`) takes one line of context and asks Claude again.
- Use `j`/`k` (or the arrow keys) to move between cards. The chips switch between Ready to approve, Needs detail, and All.

The **Outbox** tab shows approved messages in the order `send` will go through them, with "Back to review" to pull one out, and every sent note exactly as it went out. Approving only queues a message: nothing is sent until you run `linkreach send`.

The strip under the header shows what the tool is doing right now (for example "send running · last: view · Jane Doe · 3s ago"). The page refreshes every 4 seconds, and the Activity log tab has a Live toggle.

`review` shows `needs_detail` people first. Type one line of context (e.g. "spoke at Grace Hopper about AI hiring") and press Enter to redraft. A draft that fails validation can't be approved, whether from review, the dashboard, or `mark`.

On Windows, `e` opens Notepad unless you set `EDITOR` (for example `$env:EDITOR = "code --wait"`).

## Scheduling `send --auto`

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
| Only approved drafts are sent, and each is re-validated before typing | `commands/send.py` |
| Acceptance brake: 30+ requests older than 7 days below 25% disables `--auto` | `safety.py: brake_status` |
| Send fails or Pending doesn't appear → `failed`, move on | `commands/send.py` |
| Selectors fail on 3 profiles in a row → stop, screenshot, `selector_broken` | `commands/common.py: FailStreak` |
| No duplicate sends after a crash: `send_attempted_at` is committed before the click | `commands/send.py` |
| Never contact the same person twice: `profile_url` is unique and normalized; known URLs are skipped before any profile view | `db.py`, `commands/collect.py` |

## Security notes

**Browser isolation.** Dedicated profile only. Top-level navigation is allowed to `linkedin.com` and `licdn.com` (plus subdomains); anything else aborts the run, and third-party subresources are blocked. The code never calls `page.evaluate`.

**Prompt injection.** Scraped text is stripped of HTML, control, and zero-width characters and capped at 500 characters per field. Fields that contain instruction-like text, URLs, or emails are dropped from the prompt. The rest goes inside `<profile_data>` tags with a system prompt saying it's untrusted data. The model writes only the variable pieces (opener, tie line, two points). Code assembles the final messages from your templates, then `validate.py` rejects any URL other than `resume_url`, emails, phone numbers, instruction patterns ("ignore", "system prompt", "as an AI"), banned phrases, HTML, and length overruns.

**Dashboard.** Bound to `127.0.0.1:8765`. Requests with a Host header other than `127.0.0.1:8765` or `localhost:8765` get 403 (DNS rebinding). A random 32-byte token is created at each start and passed in the URL fragment, which browsers never send to the server. Every `/api` call must carry it in `X-Linkreach-Token`. No CORS headers. State changes are POST only. All data renders through `textContent`. CSP is `default-src 'self'` plus a per-launch nonce for the page's single inline `<script>` and `<style>` block (the spec asks for both a one-file page and `default-src 'self'`; the nonce lets both hold without `unsafe-inline`).

**Secrets.** API key from the keychain (or no key at all with `llm_backend: claude_code`, which uses Claude Code's own sign-in). Logs are JSON, rotate at 10 MB × 5, and pass through a redaction filter that scrubs API keys, cookies, the dashboard token, and any note/follow-up/message field. Code never logs message bodies in the first place.

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
                                   # (a simulated `send` delivers whatever you approve every ~6 s)
python scripts/demo_cli.py         # interactive terminal walkthrough with a fake LinkedIn and fake Claude
```

The tests use a fake browser (`tests/fakes.py`) and a fake Claude client (plus a fake process runner for the Claude Code backend), so they never touch LinkedIn, the API, or the real `claude` CLI. They cover caps, the brake, dedupe, status transitions, CAPTCHA stops, crash-resume, injection, dashboard hardening, and log redaction.

## Where this goes beyond the spec

- **Extra `people` columns:** `user_detail` (your one-line context from review), `validation_errors`, `send_attempted_at` (duplicate-send guard), `updated_at`.
- **Extra commands:** `init`, `login`, `set-key`, `list`.
- **Searches:** LinkedIn's People tab now ignores `?keywords=`, so `collect` reads the company's numeric id from that tab (one page view, then cached in the database for 90 days) and searches `/search/results/people/?keywords=…&currentCompany=["<id>"]`, which is current employees only. With `combine_keywords: true`, each bucket costs one page view (`"a" OR "b"`) instead of one per keyword. An alumni pass (keyword = `alumni_school`) runs first for each company.
- **Bucket shares:** `per_company_limit` is split across buckets in config order (6 over 4 buckets is 2, 2, 1, 1), so one role can't take every slot at a company. A bucket that finds fewer people than its share passes the spare slots to the next bucket in the same run. The alumni pass draws from the same shares, so alumni go first within each bucket. A search whose bucket (or company) is already full is skipped without a page view, and `collect --dry-run` shows each company's shares.
- **Approval** happens in `review` or the dashboard's Review tab. Both run the same server-side validation, and the generic status dropdown still can't set `approved`.
- **Templates** for both messages live in `config.yaml`. The model fills in the pieces, and code enforces the 280-character and 150-word limits (3 tries, then flagged for manual edit).
- **Model:** `claude-sonnet-5-5`, with server-side refusal fallbacks on (`use_refusal_fallbacks`, API backend only). Prompt caching (API backend only) covers the system prompt and background block. Very short configs may fall under the minimum cacheable size, in which case caching quietly doesn't apply.
