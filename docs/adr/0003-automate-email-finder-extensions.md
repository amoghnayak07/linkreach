# The Email finder drives the Apollo and ContactOut browser extensions

To find work emails, linkreach drives the Apollo.io extension (then ContactOut as fallback) inside the Dedicated profile, on the LinkedIn profile page it already has open. The alternatives were the user clicking "reveal" by hand (free and within both vendors' terms) or the ContactOut API (robust, but sales-gated and paid); the user chose full automation knowing that Apollo's terms forbid it (§3(f)(iv) automated access, §3(g)(ii)(2) use with LinkedIn automations), that ContactOut's likely do too, and that either vendor may ban the account.

## Consequences

- Playwright must not pass `--disable-extensions`, and the allowlist must let page subresources reach `apollo.io`, `contactout.com`, and `chrome-extension://`; top-level navigation stays LinkedIn-only.
- Each Pick tries Apollo first, then ContactOut, and is `no_email` (flagged to the user, with a field to type an email) if both fail.
- Reveals spend credits, so each extension has its own daily cap (`APOLLO_DAILY_REVEALS`, `CONTACTOUT_DAILY_REVEALS`); a capped extension is skipped.
- Apollo opens as a Chrome side panel outside the page, not an in-page panel. It's reached as an extension target via `PW_CHROMIUM_ATTACH_TO_OTHER=1`, per `.scratch/local-llm-web/issues/01`. If that route fails, the chain runs ContactOut alone until Apollo is solved.
- Extension UI breakage is a soft failure (screenshot, try the other extension, then `no_email`), unlike LinkedIn selector breakage, which stops the run.
- The Email finder is a pluggable step so a manual or API-based finder can replace it without touching the rest of the pipeline.
