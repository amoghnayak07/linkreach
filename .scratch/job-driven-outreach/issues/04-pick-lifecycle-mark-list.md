# 04: Pick lifecycle: `mark`, `list`, and the already-emailed flag

**What to build:** The user tracks outreach they did outside linkreach. `linkreach mark` moves a Pick through the lifecycle: `picked → drafted | no_email | needs_detail`; `needs_detail → drafted | no_email`; `drafted | no_email → emailed | connected` (either order, both allowed); then `replied → meeting → referral`; `dead` from anywhere. `linkreach list` shows Picks filtered by Job and status. When a Person is already `emailed` or later as a Pick on another Job, the `job` confirmation step flags them ("already emailed on <date> for <Job>") without blocking.

**Blocked by:** 03

**Status:** resolved

- [x] `mark` takes a Pick id and a status, enforces the lifecycle, rejects invalid moves with a clear message, and records history with its source
- [x] Statuses linkreach sets itself (`drafted`, `no_email`, `needs_detail`) can't be set by hand through `mark`
- [x] `list` filters by Job and by status and shows Pick id, Job, Person, status, and whether an email was found
- [x] The `job` confirmation step shows the already-emailed flag with date and Job, and the user can still keep the Pick
- [x] The old person-level statuses and transitions remain untouched for the dormant `send` path
- [x] Tests cover valid and invalid transitions, the hand-set guard, list filters, and the cross-Job flag

## Comments

**Implemented (2026-11-22).** Lifecycle lives in `db.py`: `PICK_AUTO_ONLY` (picked, drafted, no_email, needs_detail) and `PICK_MANUAL_TRANSITIONS`; `DB.set_pick_status(..., manual=True)` refuses auto-only statuses ("set by linkreach itself") and any move not in the table, naming where the Pick can go. Commands: `misc.mark_pick` / `misc.list_picks`, wired to `linkreach mark <pick_id> <status>` and `linkreach list [--job N] [--status S]`; both run without the CSV inputs. `DB.picks(job_id=None)` now lists across Jobs and joins the Job's company/role. Duplicate guard: `DB.prior_contacts` + `jobflow.contact_flags`, shown under each link in `job`'s confirm step; the Pick stays unless removed. The person-level `misc.mark` / `list_people` and `STATUSES` / `AUTO_TRANSITIONS` are unchanged (no longer on the CLI; kept for the dormant path and dashboard). README has a "Tracking progress" section.

Decisions worth a look:
- Strict ladder: `replied` only after `emailed` or `connected`; no skipping `replied → referral`. `dead` is final.
- `mark` to the current status is a no-op that exits 0.
- "Emailed or later" for the flag = the Pick's history ever hit `emailed`, `replied`, `meeting`, or `referral` (so a Pick later marked `dead` still flags). A Pick that only reached `connected` is not flagged. One that reached `replied` via `connected` without an email says "already contacted on <date> … (now <status>)" instead of "emailed". Dates are the local date of the first such history entry.
- `list` shows "found" for an email, never the address.
- `mark` accepts every Pick status at the argparse level so the hand-set guard can give its own message.

Tests: `tests/test_picks.py` (56). Full suite passes (245). `scripts/check.py` fails only at pip-audit (`backports.tarfile` unpinned in requirements.txt), which also fails on the clean tree; bandit is clean.
