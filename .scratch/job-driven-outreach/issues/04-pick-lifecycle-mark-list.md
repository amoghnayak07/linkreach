# 04: Pick lifecycle: `mark`, `list`, and the already-emailed flag

**What to build:** The user tracks outreach they did outside linkreach. `linkreach mark` moves a Pick through the lifecycle: `picked → drafted | no_email | needs_detail`; `needs_detail → drafted | no_email`; `drafted | no_email → emailed | connected` (either order, both allowed); then `replied → meeting → referral`; `dead` from anywhere. `linkreach list` shows Picks filtered by Job and status. When a Person is already `emailed` or later as a Pick on another Job, the `job` confirmation step flags them ("already emailed on <date> for <Job>") without blocking.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `mark` takes a Pick id and a status, enforces the lifecycle, rejects invalid moves with a clear message, and records history with its source
- [ ] Statuses linkreach sets itself (`drafted`, `no_email`, `needs_detail`) can't be set by hand through `mark`
- [ ] `list` filters by Job and by status and shows Pick id, Job, Person, status, and whether an email was found
- [ ] The `job` confirmation step shows the already-emailed flag with date and Job, and the user can still keep the Pick
- [ ] The old person-level statuses and transitions remain untouched for the dormant `send` path
- [ ] Tests cover valid and invalid transitions, the hand-set guard, list filters, and the cross-Job flag
