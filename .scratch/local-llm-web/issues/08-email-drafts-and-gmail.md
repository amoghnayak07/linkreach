# 08: Email drafts and Gmail

**What to build:** Adds the Email draft and Gmail draft steps to the Run for Picks that have an email. With no finder yet, the email comes from a manual entry field on the Pick, which also covers the permanent `no_email` path.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] Email call: Background, Facts, Banned phrases, Example emails, Angle and trimmed profile data → subject and body. The Job description is not included.
- [ ] Same code checks as the note, plus subject ≤ 80 characters and body ≤ 200 words; 3 attempts, then `needs_detail` with no Gmail draft
- [ ] Gmail step: creates a draft, or updates the stored `gmail_draft_id`; if that draft no longer exists, creates a new one and stores its id. No resume link or attachment.
- [ ] Picks without an email skip the Email draft and Gmail steps but still get a Connection note; status `no_email`
- [ ] On the Run page, a `no_email` Pick has an email field; saving a plausible address runs the Email draft and Gmail steps for that Pick
- [ ] Tests: draft created; redraft updates the same draft; deleted draft is recreated; validation failures → `needs_detail` with no Gmail call; manual email triggers drafting; implausible email rejected
