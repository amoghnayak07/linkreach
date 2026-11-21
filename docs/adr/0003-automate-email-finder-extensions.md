# The Email finder drives the Apollo and ContactOut browser extensions

To find work emails, linkreach drives the Apollo.io extension (then ContactOut as fallback) inside the Dedicated profile, on the LinkedIn profile page it already has open. The alternatives were the user clicking "reveal" by hand (free and within both vendors' terms) or the ContactOut API (robust, but sales-gated and paid); the user chose full automation knowing that Apollo's terms forbid it (§3(f)(iv) automated access, §3(g)(ii)(2) use with LinkedIn automations), that ContactOut's likely do too, and that either vendor may ban the account.

## Consequences

- Playwright must not pass `--disable-extensions`, and the allowlist must let page subresources reach `apollo.io`, `contactout.com`, and `chrome-extension://`; top-level navigation stays LinkedIn-only.
- Reveals spend credits, so they're capped per day across both extensions.
- Extension UI breakage is a soft failure (screenshot, try the other extension, then `no_email`), unlike LinkedIn selector breakage, which stops the run.
- The Email finder is a pluggable step so a manual or API-based finder can replace it without touching the rest of the pipeline.
