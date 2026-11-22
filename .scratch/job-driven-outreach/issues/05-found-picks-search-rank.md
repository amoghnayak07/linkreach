# 05: Found picks: search, rank, and fill to the Pick target

**What to build:** When the user supplies fewer links than the Pick target, `linkreach job` searches the company's current employees and fills the remaining slots with Found picks among the Decision-maker roles. Ranking order: likely hiring manager for the role's team → team leads and managers in that function → recruiters covering that function or location → CTO and CEO, included only when the company has 500 or fewer employees. Peers in the same role are excluded; alumni of the user's school rank first within a tier. Each Pick shows its tier and a one-line reason at the confirmation step. A Supplied pick whose current company doesn't match the Job's company gets a warning but is kept.

**Blocked by:** 03

**Status:** resolved

- [x] `pick_target` config (default 5) and a `--picks N` override; when Supplied picks meet or exceed the target, no search runs and no page view is spent on it
- [x] Search reuses the existing company-id lookup and cache and the current-employees people search; queries come from the Job's role, function, and team plus Decision-maker role keywords; the per-Job search budget is small, fixed, and counted against the daily page-view cap
- [x] Company size is read from the page the id lookup already visits where possible and only decides CTO/CEO eligibility
- [x] Claude ranks sanitized candidate cards and returns tier plus reason; code enforces tier rules, peer exclusion, the CTO/CEO size rule, and the target count
- [x] People already known to the database are skipped before any profile view, as today
- [x] The confirmation step lists Supplied picks first, then Found picks with tier and reason, and lets the user remove or add
- [x] Company-mismatch warning for Supplied picks
- [x] Tests through the `job` command cover: fill to target, no search when target met, more Supplied picks than target, tier ordering, peer exclusion, CTO/CEO included at ≤ 500 and excluded above, alumni ordering within a tier, mismatch warning, search budget respected

## Comments

**Implemented (2026-11-22).** New `jobsearch.py`: `plan_queries` → `find_picks` (id+size lookup, at most `SEARCH_BUDGET` = 4 people searches, known/supplied/suspicious cards dropped before ranking) → `rank_with_claude` (one structured call on the injectable client; cards fenced in `<candidates>`, no names sent) → `enforce` (code rules). `jobflow.search_found_picks` opens the browser for the search; `jobflow.add_found_picks` saves Found picks with tier and reason after the Supplied ones. `commands/job.py`: `--picks N` (0–15), company-page prompt, `confirm_picks` (Supplied first, then Found with tier, reason, alumni tag). `LinkedIn.company_info` returns (id, employees) from the one People-tab view; `parse_company_size` reads "51-200 employees" / "10K+ employees" / "N associated members" from page text (no new selectors). DB: `company_ids.employees` (migrated), new `company_pages` table (company name → confirmed slug), `ensure_person` takes title and alumni. Mismatch check: `jobflow.company_mismatch` on headline + top-card text (`Profile.topcard`), warning printed per Pick and in the report, Pick kept.

Decisions worth a look:
- **Company page.** A Job only has a company *name*, but the id lookup needs the LinkedIn company slug. Before searching, `job` asks for the company page with a default (the page used last time for that name, else a slug guessed from the name). Enter accepts, a pasted link replaces it, `-` skips the search. It's remembered only once the id lookup succeeds. If the id can't be read, no search runs (the old-UI keyword fallback could return other companies' people).
- **Queries, in budget order:** `"<team>" AND (manager OR lead OR director OR head)`, `"<function>" AND (…)` (function mapped from the role title, e.g. PM → "product"), recruiters / talent acquisition / sourcer, CTO/CEO (small companies only), `"<alumni_school>" AND (… OR recruiter)`. Budget 4 cuts the last. Everyone the alumni search returns is marked alumni.
- **Size rule:** a range counts as its upper end, so "201-500 employees" is small and "501-1,000" isn't. Unknown size counts as large (CTO/CEO left out, and the terminal says so). Size is cached with the id; ids cached by the old `collect` have no size until they expire.
- **Code over Claude:** CTO/CEO titles are always tier `executive` (dropped at large companies); Claude's `executive` on any other title becomes `lead_manager`. A peer means the same core title once level words are removed ("Senior Product Manager" vs "Product Manager II"); "Group Product Manager" isn't a peer. Reasons that look like instructions/URLs fall back to the tier label.
- **Claude ranking failure:** falls back to tiers from title keywords, with a terminal note, so the run continues.
- **Stops during the search** (CAPTCHA, cap) end the run before the Job is saved, with "Nothing was saved."
- **Alumni flag:** processing now keeps an existing `is_alumni` instead of overwriting it when the profile shows no education.
- **Mismatch:** only flagged when the headline/top card has text and doesn't contain the company name (suffixes like Inc/Corp ignored). It's a heuristic and hasn't been checked against the live top card.

Tests: `tests/test_job_search.py` (45). Ticket-03/04 tests are pinned to `pick_target: 1` (autouse fixture) since they cover Supplied picks only. New fakes: `KeywordSearchPage` (results depend on the query), `company_page(..., employees=)`, ranking in `job_responder(rank=)`. Full suite passes (316); `scripts/check.py` passes (pip-audit and bandit).
