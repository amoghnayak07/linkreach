# 10: `doctor` checks for the new flow

**What to build:** Before spending page views or credits, the user can run `linkreach doctor` and see everything the new flow needs: Gmail access, both extensions loaded and signed in with working selectors, and the Style file. `login` guides the user through installing and signing in to the extensions.

**Blocked by:** 07, 09

**Status:** ready-for-agent

- [ ] `doctor` reports: Gmail token missing or unusable; Apollo / ContactOut not loaded, not signed in, or panel selectors not matching on the check profile; Style file missing or missing a required section
- [ ] Each failure prints a one-line fix (for example "run `linkreach gmail-login`", "sign in to Apollo via `linkreach login`")
- [ ] The extension checks spend no Reveal credits
- [ ] `doctor` checks that existed for the old flow but no longer apply (CSV inputs, brake and request caps while `connect_mode` is manual) are skipped or reworded
- [ ] `login`'s instructions mention installing and signing in to Apollo and ContactOut in the Dedicated profile
- [ ] Tests cover each new failure, the all-green case, and that no Reveal event is logged
