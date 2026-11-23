# 01: Apollo side-panel spike

**What to build:** A throwaway probe (alongside `.scratch/job-driven-outreach/probe_extensions.py`) that finds a reliable way to open Apollo's Chrome side panel on a LinkedIn profile under Playwright and read an email from it. Record the findings in `extension-findings.md`. This decides how issue 10 reaches Apollo.

**Blocked by:** none

**Status:** ready-for-human (needs the Dedicated profile signed in to LinkedIn and Apollo, and spends at most one or two Apollo credits)

- [ ] Launch with `PW_CHROMIUM_ATTACH_TO_OTHER=1` set in the environment before Playwright starts, and confirm whether the side panel's `chrome-extension://` target appears in `context.pages`
- [ ] Try three ways to open the panel and record which work:
  - (a) Apollo's keyboard shortcut set in `chrome://extensions/shortcuts`, pressed via `page.keyboard.press`. This may not fire, because extension shortcuts are handled by the browser window, not the page.
  - (b) the panel kept pinned open in the Dedicated profile
  - (c) clicking Apollo's in-page launcher inside its shadow root
- [ ] For the way that works: stable selectors for "access/view email" and the revealed `mailto:` link, and whether the panel follows tab navigation to the next profile
- [ ] Confirm ContactOut still works under the same launch settings
- [ ] Result recorded: either "Apollo works via X" with selectors, or "Apollo blocked", in which case issue 10 ships with ContactOut alone and Apollo stays open
