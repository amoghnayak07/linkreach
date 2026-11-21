# 02: Check the extensions live in the Dedicated profile (needs the user)

**What to build:** Proof, on the user's machine, that the Apollo.io and ContactOut extensions work inside the Dedicated profile when linkreach drives it, plus the selectors needed to Reveal and read a work email from each one's panel on a LinkedIn profile page. This is a hands-on session with the user (they sign in and watch); it produces findings and selectors, not the Email finder itself (ADR-0003).

**Blocked by:** None (can start immediately)

**Status:** ready-for-human

- [ ] The user has opened the Dedicated profile via `linkreach login`, installed Apollo and ContactOut from the Chrome Web Store, and signed in to LinkedIn, Apollo, and ContactOut there
- [ ] Confirmed: with Playwright's disable-extensions default removed, both extensions load in the automated browser and their panels appear on a LinkedIn profile page
- [ ] Confirmed which extension traffic the current domain filter blocks, and that allowing page subresources to `apollo.io`, `contactout.com` (and subdomains) and `chrome-extension://`, while keeping top-level navigation LinkedIn-only, is enough for both panels to work
- [ ] For each extension: how the panel is reached (page DOM, open shadow root, or iframe), selectors to open it, trigger a Reveal, read the revealed email, and recognize "no email found" and "not signed in" states, each recorded as a fallback list
- [ ] Whether a Reveal spends a credit when nothing is found, for each vendor
- [ ] Screenshots of each state saved under `.scratch/job-driven-outreach/` and findings written to `.scratch/job-driven-outreach/extension-findings.md`
- [ ] Any finding that contradicts ADR-0003 or the spec is flagged in the findings file
