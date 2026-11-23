# 10: Email finder chain (Apollo → ContactOut)

**What to build:** The "email found" step. For each Pick, try Apollo, then ContactOut (ADR-0003), using the route and selectors from issue 01. If both fail, the Pick is `no_email` and clearly flagged. Replaces old issues 08 and 09 of job-driven-outreach.

**Blocked by:** 01, 07

**Status:** ready-for-agent

- [ ] The browser launch keeps extensions enabled, uses the sandbox, allows only the known extension ids, and sets `PW_CHROMIUM_ATTACH_TO_OTHER=1` if issue 01 needs it; top-level navigation stays LinkedIn-only
- [ ] Apollo finder per issue 01's route; ContactOut finder via its in-page iframe `data-testid` selectors; both behind the `EmailFinder` protocol with panel-scoped selectors
- [ ] Separate daily Reveal caps, `APOLLO_DAILY_REVEALS` and `CONTACTOUT_DAILY_REVEALS`, with hard ceilings in code; a capped finder is skipped
- [ ] Each Reveal is logged per finder; the found email is format-checked; the Pick records which finder found it; emails are never logged
- [ ] Panel missing or broken → screenshot, `finder_broken` event, next finder; "not signed in" is reported once per Run
- [ ] Both fail → `no_email`, flagged on the Run page with the reason from each finder and the manual email field from issue 08
- [ ] If issue 01 found Apollo blocked: the chain runs ContactOut alone and the Setup page says Apollo is unavailable
- [ ] Tests: Apollo hit; Apollo miss then ContactOut hit; both miss; Apollo capped; panel missing; not signed in; off-domain navigation still stops the Run
