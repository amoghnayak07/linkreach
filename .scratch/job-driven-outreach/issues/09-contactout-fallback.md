# 09: ContactOut fallback

**What to build:** When Apollo finds no email for a Pick, or its panel is broken or signed out, linkreach tries the ContactOut extension on the same open profile before giving up, so more Picks end up with an email. Both extensions share the same daily Reveal cap.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] A ContactOut implementation of the Email finder interface using the selectors and findings from 02, with a panel-scoping test like Apollo's
- [ ] Order is Apollo, then ContactOut; ContactOut is only tried when Apollo returns nothing or fails
- [ ] ContactOut Reveals count against the same `reveal_cap`; the cap is checked before each attempt
- [ ] ContactOut panel failures are soft (screenshot, `finder_broken`, continue), same as Apollo
- [ ] The end-of-run summary shows Reveals used per extension and how many emails each found
- [ ] Tests cover: Apollo finds → ContactOut not tried; Apollo empty → ContactOut finds; both empty → `no_email`; Apollo broken → ContactOut finds; cap reached between the two attempts
