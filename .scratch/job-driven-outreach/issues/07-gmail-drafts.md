# 07: Gmail drafts

**What to build:** Every drafted Pick that has an email gets an Email draft in the user's Gmail Drafts folder, which they review and send themselves. `linkreach gmail-login` runs Google's installed-app sign-in for the user's own OAuth desktop client with only the compose scope and stores the refresh token in the OS keychain. linkreach only ever creates drafts and never sends.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] A Gmail drafts client interface with one operation, "create draft (to, subject, body) → draft id", injected through the command context; a fake that records drafts is added to the test fakes
- [ ] The real implementation uses the Gmail API with the compose scope only; nothing in linkreach calls send
- [ ] `gmail-login` takes the user's OAuth client file, runs the consent flow, stores the refresh token in the keychain, and never writes the token to disk or logs
- [ ] README documents creating the Google Cloud OAuth desktop client and running `gmail-login`
- [ ] After validation passes and an email exists, the Gmail draft is created, its id stored on the Pick, and the Pick moves to `drafted`; a Pick without an email gets no draft and stays `no_email`
- [ ] A Gmail failure for one Pick is logged (without content), leaves that Pick retryable, and doesn't stop the run
- [ ] `job` refuses to start with a clear message when no Gmail token is stored
- [ ] Any new dependency is pinned with hashes in the lock files and passes the existing audit check
- [ ] Tests through the `job` command (using an Email finder fake that returns emails) cover: draft created with the right to/subject/body, no draft without an email, Gmail failure for one Pick, missing token refusal
