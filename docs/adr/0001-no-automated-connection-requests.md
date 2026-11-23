# linkreach doesn't send connection requests

linkreach only presents and stores Connection notes; the user sends every request themselves. Automated sending is the biggest LinkedIn account risk.

The automated path was first kept but switched off (`connect_mode: manual`) in case a safer route turned up. When the CLI was replaced by the web app (ADR-0005), it was deleted instead: the `send` and `sync` commands, the connect selectors, the acceptance brake, request caps and `send_attempted_at`. Dormant code that isn't kept up to date is a risk if it's switched back on by accident, and reviving it would have meant rewriting it anyway. The Connection notes view has a "sent" checkbox the user ticks by hand.
