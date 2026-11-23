# 05: Setup page

**What to build:** A Setup page that replaces `doctor`, `login` and `gmail-login`. It shows a pass/fail row per dependency with how to fix it, plus the two actions needing a browser: LinkedIn login and Gmail connect.

**Blocked by:** 02, 03, 04

**Status:** ready-for-agent

- [ ] Checks:
  - Postgres reachable and migrated
  - Ollama reachable and the configured model pulled
  - Profile file present and valid (issue 04 messages)
  - Gmail token present and refreshable
  - LinkedIn session valid
  - Apollo and ContactOut signed in
  - Each runs on demand; browser checks open the Dedicated profile only when asked
- [ ] "Log in to LinkedIn" opens the Dedicated profile with no automation, as `login` does today, so the user can sign in and install and sign in to the extensions
- [ ] Upload a Google OAuth desktop client file, stored at `~/.linkreach/`; "Connect Gmail" runs the existing loopback PKCE flow with compose scope only and stores the refresh token in the keychain
- [ ] Tests (fakes): each check's failure is reported; Gmail connect stores a token; client upload rejects a non-desktop or invalid file
