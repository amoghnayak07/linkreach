# 11: Remove the old bulk flow and hide the dashboard's Review and Outbox tabs

**What to build:** linkreach has one flow. The company-driven bulk path is deleted: the `collect`, `draft`, and `review` commands, the company and job CSV inputs, buckets and their shares, the alumni pass, the LinkedIn follow-up message (template and limits), and the 1,000+ employee rule. The search and company-id code the new flow reuses stays. The dashboard still starts cleanly, with its Review and Outbox tabs hidden, since they depend on the deleted drafting path and phase 2 replaces them.

**Blocked by:** 01, 05, 06

**Status:** ready-for-agent

- [ ] `collect`, `draft`, and `review` are gone from the CLI; `init` no longer copies CSVs; the `--inputs` folder only needs config (and the Style file lives at the repo root)
- [ ] Config no longer has buckets, `per_company_limit`, `combine_keywords`, alumni-pass settings, or the note and follow-up templates; old configs fail validation with a clear message naming the removed keys
- [ ] The dormant `send` path (ADR-0001) still loads and its tests still pass with `connect_mode: automated`, or the tests that only covered deleted code are removed
- [ ] The dashboard starts, opens without errors, and doesn't show or serve the Review and Outbox tabs or their endpoints; the Activity log tab still works
- [ ] Tests that only covered deleted code are removed; the full suite and the audit/security check pass
- [ ] README describes only the new flow (setup, `job`, `mark`, `list`, `gmail-login`, `doctor`) and notes the switched-off send path and hidden dashboard tabs
- [ ] The example config and the demo scripts no longer reference removed settings or commands
