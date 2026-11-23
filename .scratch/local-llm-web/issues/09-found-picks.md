# 09: Found picks in the Run

**What to build:** Move the existing Found-pick search and ranking (`jobsearch.find_picks`) into the Run, ranked by the local model. Found picks go straight on to the per-Pick steps with no approval stop.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] When there are fewer Supplied picks than the Pick target, the Run searches before the per-Pick steps; with enough Supplied picks, there's no search
- [ ] Rank call goes through the local model; code still enforces tier order, alumni first, no peers, CTO/CEO only at ≤ 500 employees, and the target count
- [ ] Rank prompt fits the token budget, splitting the candidate cards across calls if needed
- [ ] Found picks appear on the Run page with tier and reason
- [ ] The existing `test_job_search.py` scenarios are ported to the HTTP seam
