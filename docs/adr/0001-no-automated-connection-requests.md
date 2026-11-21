# linkreach stops sending connection requests, but keeps the code

linkreach now only presents and stores Connection notes; the user sends every request themselves. Automated sending (the `send` command, connect selectors, the acceptance brake, request caps, `send_attempted_at`) is the biggest LinkedIn account risk, so it's switched off by a `connect_mode: manual` default rather than deleted, because the user wants it available if a safer route turns up. The dormant code isn't updated as the data model changes, so reviving it later means bringing it up to date first.
