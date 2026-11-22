# 07: Gmail drafts

**What to build:** Every drafted Pick that has an email gets an Email draft in the user's Gmail Drafts folder, which they review and send themselves. `linkreach gmail-login` runs Google's installed-app sign-in for the user's own OAuth desktop client with only the compose scope and stores the refresh token in the OS keychain. linkreach only ever creates drafts and never sends.

**Blocked by:** 03

**Status:** resolved

- [x] A Gmail drafts client interface with one operation, "create draft (to, subject, body) → draft id", injected through the command context; a fake that records drafts is added to the test fakes
- [x] The real implementation uses the Gmail API with the compose scope only; nothing in linkreach calls send
- [x] `gmail-login` takes the user's OAuth client file, runs the consent flow, stores the refresh token in the keychain, and never writes the token to disk or logs
- [x] README documents creating the Google Cloud OAuth desktop client and running `gmail-login`
- [x] After validation passes and an email exists, the Gmail draft is created, its id stored on the Pick, and the Pick moves to `drafted`; a Pick without an email gets no draft and stays `no_email`
- [x] A Gmail failure for one Pick is logged (without content), leaves that Pick retryable, and doesn't stop the run
- [x] `job` refuses to start with a clear message when no Gmail token is stored
- [x] Any new dependency is pinned with hashes in the lock files and passes the existing audit check
- [x] Tests through the `job` command (using an Email finder fake that returns emails) cover: draft created with the right to/subject/body, no draft without an email, Gmail failure for one Pick, missing token refusal

## Comments

**Implemented (2026-11-22), together with 06.** New `linkreach/gmail.py`: `GmailDrafts` protocol (`create_draft(to, subject, body) -> id`), `ApiGmail` (refresh-token → access token, cached in memory; `POST users/me/drafts` with a base64url RFC 2822 message), `make_client()` (raises `GmailNotSignedIn` with no stored sign-in), and `login()` (installed-app flow: loopback `127.0.0.1` redirect on a random port, PKCE S256, `state` check, `access_type=offline`, `prompt=consent`). `Ctx.gmail` injects the client; `None` means the real one from the keychain. `tests/fakes.FakeGmail` records `(to, subject, body)` and can fail for chosen recipients.

The shared finish step is `jobflow.finish_pick(ctx, pick, draft, email, gmail)`: saves email, subject, body, and note; no email → `no_email`; email → Gmail draft, id stored, `drafted`. Both `job` (`_process_pick`) and 06's `redraft_pick` call it.

Decisions worth a look:
- **No new dependency.** The Gmail client and the OAuth flow use only the standard library (`urllib`, `http.server`, `email`), so `google-auth-oauthlib` / `google-api-python-client` stay out of the lock files and the "allowed runtime list" in the README holds. The lock-file checkbox is ticked because there was nothing to pin.
- **What's in the keychain:** one entry, `linkreach` / `GMAIL_OAUTH`, holding JSON with the client id, client secret (not really secret for desktop clients, but kept off disk anyway), and refresh token. The refresh token, client secret, and every access token are registered with the log redaction filter.
- **Scope check:** `gmail-login` refuses to store anything if Google grants any scope other than `gmail.compose`. A test scans the package for `messages/send` and `drafts/send`.
- **Gmail failure = retryable:** the draft, note, and email are saved, the status doesn't move (`picked`, or `needs_detail` for a redraft), and `activity_log` gets `pick N: gmail draft failed (GmailError)`. The note is still printed. `linkreach redraft` retries every Pick in that state first, without asking (`jobflow.gmail_pending` / `retry_gmail`). An expired or revoked sign-in (`invalid_grant`) becomes `GmailNotSignedIn` with "run `linkreach gmail-login` again".
- **Refusal order in `job`:** Style file, then Gmail sign-in, then the Claude client, all before the description is read. `redraft` refuses the same way when it has work.
- **Testing-mode consent screens expire refresh tokens after 7 days.** The README says so. `doctor` checking the token is ticket 10.
- Not verified against live Google: the consent flow and drafts call are covered by tests with faked HTTP (the loopback server itself runs for real in the tests). Do one real `gmail-login` + `job` before relying on it.

Tests: `tests/test_gmail_drafts.py` (13). Existing `job` tests updated for the new summary line (`… drafts N, Gmail drafts N, needs detail N, failures N …`). Full suite passes (341); `scripts/check.py` passes.
