# Extension findings (issue 02)

Live session on the user's machine, Windows 11, Google Chrome via Playwright `launch_persistent_context`, Dedicated profile `~/.linkreach/chrome-profile`. Probe: `probe_extensions.py`.

## Setup notes

- `linkreach login` hung after the window closed: the installed extensions kept Chrome alive in the background, so `open_plain_chrome`'s `subprocess.run` never returned. Fix used: end the profile's `chrome.exe` processes, and turn off "Continue running background apps when Google Chrome is closed" in `chrome://settings/system` in the Dedicated profile. **Follow-up for 10:** `login`'s instructions should mention this setting.
- Playwright launches Chrome with `--no-sandbox` unless `chromium_sandbox=True` (Chrome shows an "unsupported command-line flag" banner). `PlaywrightSession` (`linkreach/browser.py:157`) has this today. **Follow-up for 08:** pass `chromium_sandbox=True` when the launch args are changed.

## Run 1: strict filter (LinkedIn-only), extensions enabled

- With `ignore_default_args=["--disable-extensions"]`, **both extensions load** in the automated browser. Service workers seen at launch:
  - `chrome-extension://alhgpfoeiimagjlnfekdhkjlkiomcapa/…serviceWorker….js` (believed Apollo; confirm in `chrome://extensions`)
  - `chrome-extension://jjdemeiffadmmjhkbbpglgnlgeafomjo/app/background.js` (believed ContactOut; confirm)
- **Both panels render as broken frames** under the strict filter.
- Blocked requests (591 total, all subresources, no top-level navigations):
  - 568 × `chrome-extension://invalid` fetches: probably LinkedIn's page probing for installed extensions. Not needed by the panels. Allowing `chrome-extension://` will let these through; they fail on their own, but LinkedIn can then see which extensions are installed. **Flag:** consider allowing only the two known extension IDs instead of all of `chrome-extension://`.
  - Documents (iframes): `app.apollo.io`, `contactout.com`: the panels are vendor-origin iframes (to be confirmed in run 2).
  - Fetches: `extension.apollo.io`, `assets.apollo.io`, `contactout.com`.
  - Apollo's own `chrome-extension://alhgpfoe…` scripts and image.
  - Vendor telemetry: `track.customer.io`, `o949158.ingest.sentry.io`, `www.google.com` (script). Not on the proposed allowlist.
  - LinkedIn anti-bot: `li.protechts.net`, `cs.ns1p.net`. Already blocked today, unrelated to this test.

## Run 2: relaxed filter (first pass, no interaction)

- No `--no-sandbox` banner with `chromium_sandbox=True`.
- **ContactOut panel loads and works**: frames `contactout.com/extension/app/` and `contactout.com/extension/action_button/<n>`, then fetches `contactout.com/api/v5/profiles/encrypted` (profile lookup). Note: it also fetches `contactout.com/api/linkedin/selectors`, so it downloads its LinkedIn selectors remotely.
- **Apollo authenticates** (`extension.apollo.io/api/v1/auth/chrome_extension_initial_auth`, `…_everywhere_auth`) but **its panel did not open** (no `app.apollo.io` document this time, unlike run 1). Apollo probably needs a click on its launcher to open the sidebar.
- Still blocked, and ContactOut didn't need any of it: `fonts.googleapis.com`, `o949158.ingest.sentry.io`, `edge.fullstory.com`, `www.googletagmanager.com`, `www.google.com/recaptcha/enterprise.js` (unclear whose), LinkedIn anti-bot hosts.
- `chrome-extension://invalid` probes: 115 (allowed under relaxed; they fail on their own).

## Run 2b: relaxed filter, manual Reveal

- **ContactOut Reveal works** under the relaxed filter: a work email appeared, with a "Verified" label next to it (value not recorded here).
- Inspector's suggested locator was `locator("iframe").nth(3).content_frame.get_by_text("<email>Verified")`: not usable (position-based iframe, text-based on the value). Structural selectors to come from redacted DOM snapshots (`~/.linkreach/probe/`, outside the repo).
- **The Reveal's network calls did not appear in the request log.** Only the panel's initial load did. So the Reveal goes through the extension's background service worker, which `context.route` doesn't see. **Flag for 08 / security notes:** the domain filter governs the page and its frames, not the extensions' own background traffic.
- **Apollo's panel did not open** on this profile; the user suspects Apollo has no record of him. To retest on a profile Apollo likely knows.

- Credits: user chose not to measure credit use on a miss. **Unmeasured** (issue 02 item left open on purpose).
- **Apollo panel never opens under automation**, even on a profile Apollo should know, though the extension starts, authenticates (`extension.apollo.io/.../auth` calls succeed), and draws its launcher icon. It never requests its `app.apollo.io` frame in relaxed runs (it did, and was blocked, 4× in the strict run).
- **Apollo opens fine in plain Chrome on the same Dedicated profile** (`linkreach login`). So it's not a sign-in problem; it's something about the automated launch: the route filter itself, or Playwright's default Chrome flags (e.g. `--enable-automation`). Bisecting with probe modes `open` (no filter) and `bare` (no filter, no default flags).

## Run 3: `open` mode (no filter at all, Playwright default flags)

- **Apollo panel still does not open**, so the route filter is not the cause. Apollo never requests `app.apollo.io`.
- Apollo console: `[Apollo] Lean LinkedIn content script injected`, `[WindowMode] detectAndStoreWindowModeAvailability {windowModeAvailable: false}`. Hypothesis: current Apollo opens in **Chrome's side panel** (outside the page), not as an in-page iframe. If so, a Playwright page/frame locator can't reach it, which **contradicts ADR-0003's assumption** that both extensions are driven through an in-page panel. To confirm with the user + `bare` mode.
- With no filter, LinkedIn's anti-bot hosts (`*.protechts.net`, `*.ns1p.net`) and reCAPTCHA load normally; ContactOut is unaffected either way.

- **Confirmed by the user: Apollo opens as a Chrome sidebar (side panel), not an in-page panel.** Its UI is an extension page in the browser chrome, outside LinkedIn's DOM, so linkreach's page/frame locators can't reach it, and the side panel can only be opened by a user gesture. Under automation it never opened at all.
- `bare` mode (all Playwright default flags dropped) failed to launch (Chrome exits immediately: the flags Playwright needs to drive Chrome were dropped too). Not pursued: it can't change the conclusion above.
- User chose to **investigate side-panel automation** before re-planning.
- From Apollo 17.2.3's manifest and LinkedIn content script (read from the Dedicated profile on disk):
  - `sidePanel` permission; side panel page `c32hg_rNdM_side-panel….html` (not web-accessible). There is also a web-accessible `iqaco_rNdM_linkedin-sidebar….html`, possibly an older in-page mode.
  - The content script injects an **in-page launcher**: `div#<id>[data-cy="apollo-opener-icon-new"]` → **open** shadow root → `button[aria-label="Toggle Apollo side panel"]`. Clicking it sends `{type: "toggle_side_panel"}` to the service worker, which opens the side panel. A Playwright click is a trusted gesture, so this may open the side panel under automation.
  - `[WindowMode]` / `windowModeAvailable` is only Arc-browser detection (`--arc-palette-title`); irrelevant.
  - The "Lean LinkedIn" script also answers `LINKEDIN_GET_SEARCH_RECORDS` messages (Apollo scrapes LinkedIn search results).
- Probe mode `sidepanel` clicks the launcher, then checks whether the side panel is reachable via `ctx.pages`, the DevTools target list, or `connect_over_cdp`.
- **⚠ Contradicts ADR-0003** (both vendors via in-page extension panels) and issue 08 (Apollo panel modelled as elements on the profile page). Needs a decision before 08 is implemented.

## ContactOut panel structure (from redacted snapshots)

- In-page **iframes injected into LinkedIn's DOM**, no shadow root. No stable `id` or `src` attribute on the `<iframe>` element (id is random, e.g. `qaH1sxl`; styles are inline). Reach them by **frame URL** instead:
  - panel: `https://contactout.com/extension/app/` (320×640, fixed, slides in from the right)
  - launcher tab: `https://contactout.com/extension/action_button/<n>` (32×84 purple tab, `.floating-button`)
- Inside the panel (React, hashed `css-*` classes are unstable; `data-testid` attributes are stable-looking):
  - contact row: `[data-testid="contact-row-container"]`; email rows have `.category-badge .co-mail`, phone rows `.co-phone`
  - email text: the row's `span` (also present in the row's `data-for` attribute)
  - verified marker: `[data-testid="indicator"][data-tip="Verified"]`
  - reveal buttons: `button.reveal-button` / `[aria-label="Reveal Button"]`; phones: `[data-testid="reveal-phones"]` ("View phone"). Email-reveal button not yet captured (Aldo's emails were already revealed, and ContactOut keeps them revealed). Expect `data-testid="reveal-emails"`, to confirm on an unrevealed profile.
  - header: `[data-testid="header-logo"]` (title carries the version, e.g. `ContactOut v5.6.18`), `[data-testid="menu-button"]`, `[data-testid="rollup-button"]`
  - "Find work email" section button exists below the contact rows
- Probe bug: the phone redaction also masks large `z-index` values and some hex hashes. Harmless.

## Run 2c: DOM snapshots and remaining states

_Pending._ To record per extension: panel attachment (DOM / shadow root / iframe + src), selectors (open panel, Reveal, email, no-email state, signed-out state), credit spent on a miss, any still-blocked request the panel needs, off-domain navigation check.
