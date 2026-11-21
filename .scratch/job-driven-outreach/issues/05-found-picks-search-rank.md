# 05: Found picks: search, rank, and fill to the Pick target

**What to build:** When the user supplies fewer links than the Pick target, `linkreach job` searches the company's current employees and fills the remaining slots with Found picks among the Decision-maker roles. Ranking order: likely hiring manager for the role's team → team leads and managers in that function → recruiters covering that function or location → CTO and CEO, included only when the company has 500 or fewer employees. Peers in the same role are excluded; alumni of the user's school rank first within a tier. Each Pick shows its tier and a one-line reason at the confirmation step. A Supplied pick whose current company doesn't match the Job's company gets a warning but is kept.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] `pick_target` config (default 5) and a `--picks N` override; when Supplied picks meet or exceed the target, no search runs and no page view is spent on it
- [ ] Search reuses the existing company-id lookup and cache and the current-employees people search; queries come from the Job's role, function, and team plus Decision-maker role keywords; the per-Job search budget is small, fixed, and counted against the daily page-view cap
- [ ] Company size is read from the page the id lookup already visits where possible and only decides CTO/CEO eligibility
- [ ] Claude ranks sanitized candidate cards and returns tier plus reason; code enforces tier rules, peer exclusion, the CTO/CEO size rule, and the target count
- [ ] People already known to the database are skipped before any profile view, as today
- [ ] The confirmation step lists Supplied picks first, then Found picks with tier and reason, and lets the user remove or add
- [ ] Company-mismatch warning for Supplied picks
- [ ] Tests through the `job` command cover: fill to target, no search when target met, more Supplied picks than target, tier ordering, peer exclusion, CTO/CEO included at ≤ 500 and excluded above, alumni ordering within a tier, mismatch warning, search budget respected
