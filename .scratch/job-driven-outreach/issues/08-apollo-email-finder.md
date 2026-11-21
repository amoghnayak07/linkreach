# 08: Apollo email finder

**What to build:** For each confirmed Pick, while its LinkedIn profile is open in the Dedicated profile, linkreach uses the Apollo.io extension to Reveal a work email (ADR-0003), using the selectors and findings from 02. Reveals are capped per day; a broken or missing Apollo panel is a soft failure, unlike a LinkedIn selector failure or CAPTCHA, which still stops the run.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] The automated browser launch no longer disables extensions; the request filter allows page subresources to `apollo.io`, `contactout.com` (and subdomains) and `chrome-extension://`; top-level navigation outside LinkedIn still aborts the run; the README's security notes are updated
- [ ] An Apollo implementation of the Email finder interface using fallback-list selectors kept with the other selectors; a test enforces that its selectors are scoped to the Apollo panel, never page-wide
- [ ] Each Reveal attempt is logged as its own activity event and counted against `reveal_cap` (config, default 15 per day, with a hard ceiling config can't raise); once the cap is reached, remaining Picks become `no_email` and the run continues
- [ ] A revealed email is format-checked before it's stored; an implausible value is treated as no email
- [ ] Panel missing or changed → screenshot, `finder_broken` event, Pick becomes `no_email`, run continues
- [ ] "Not signed in" in the panel is reported clearly once, and remaining Picks skip Reveal
- [ ] Revealed emails are never logged
- [ ] Tests (Apollo panel modelled as elements on fake profile pages) cover: email found, no email found, cap reached mid-run, panel missing, not signed in, off-domain navigation still stopping the run
