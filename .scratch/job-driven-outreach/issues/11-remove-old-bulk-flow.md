# 11: Remove the old bulk flow and hide the dashboard's Review and Outbox tabs

**What to build:** linkreach has one flow. The company-driven bulk path is deleted: the `collect`, `draft`, and `review` commands, the company and job CSV inputs, buckets and their shares, the alumni pass, the LinkedIn follow-up message (template and limits), and the 1,000+ employee rule. The search and company-id code the new flow reuses stays. The dashboard still starts cleanly, with its Review and Outbox tabs hidden, since they depend on the deleted drafting path and phase 2 replaces them.

**Blocked by:** 01, 05, 06

**Status:** resolved

- [x] `collect`, `draft`, and `review` are gone from the CLI; `init` no longer copies CSVs; the `--inputs` folder only needs config (and the Style file lives at the repo root)
- [x] Config no longer has buckets, `per_company_limit`, `combine_keywords`, alumni-pass settings, or the note and follow-up templates; old configs fail validation with a clear message naming the removed keys
- [x] The dormant `send` path (ADR-0001) still loads and its tests still pass with `connect_mode: automated`, or the tests that only covered deleted code are removed
- [x] The dashboard starts, opens without errors, and doesn't show or serve the Review and Outbox tabs or their endpoints; the Activity log tab still works
- [x] Tests that only covered deleted code are removed; the full suite and the audit/security check pass
- [x] README describes only the new flow (setup, `job`, `mark`, `list`, `gmail-login`, `doctor`) and notes the switched-off send path and hidden dashboard tabs
- [x] The example config and the demo scripts no longer reference removed settings or commands

## Comments

**Implemented (2026-11-22).**

- Deleted: `commands/collect.py`, `commands/review.py`, `drafting.py`, `examples/companies.example.csv`, `examples/jobs.example.csv`, and the tests that only covered them (`test_collect.py`, `test_collect_quota.py`, `test_draft.py`, `test_dashboard_review.py`). Also `llm.max_parallel` (only `draft` used it).
- Config: `config.yaml` is the only input file; `Inputs` holds just the config, and leftover CSVs are ignored. `config.REMOVED_KEYS` turns `buckets`, `per_company_limit`, `combine_keywords`, `alumni_angle`, `exclude_title_keywords` (collect-only), `templates`, and `followup_max_words` into one line each: "config.yaml: buckets: removed setting (…); delete it from config.yaml". `follow_up_delay_days` stays: the dormant `sync`/`send` use it.
- Dormant send: now validates the note alone (`validate.validate_note`, replacing `validate_draft`/`check`) and orders by alumni, then id (no company priority without `companies.csv`). All send/sync tests pass with `connect_mode: automated`; added one for a note that no longer validates.
- Dashboard: the Review and Outbox tabs **and** the Follow-ups tab are removed, along with their endpoints (review, validate, approve, decline, unapprove, draft, redraft, outbox, followups, followup done/snooze/regenerate). The spec said "hide" for this phase; I deleted the code instead, because every one of those endpoints imported the deleted `drafting.py`, and Follow-ups depended on the removed follow-up message. Companies now reads from the database only (no priority column). Run labels track `job`, `send`, `sync`, `doctor`. The page opens on People.
- `test_claude_code.py`: tests that ran the backend through `run_draft` now go through `JobDrafter`; the two parallel-limit tests went with `draft`.
- `test_logs.py`: the end-to-end redaction check now runs `job` (with a found email and a Gmail draft) plus the dormant `send`.
- Demos: `scripts/demo_cli.py` walks through `job` (search, ranking, injection dropped, Gmail drafts, a `needs_detail` Pick), `redraft`, a CAPTCHA stop, `mark`, `list`. `scripts/demo_dashboard.py` seeds sample people and a stopped `job` run.
- Person-level DB columns (`bucket`, `followup_draft`, `user_detail`) stay in the schema for existing databases; nothing writes them.

Full suite: 297 passed. `scripts/check.py`: passed.
