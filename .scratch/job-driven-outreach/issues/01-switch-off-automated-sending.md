# 01: Switch off automated sending

**What to build:** linkreach no longer offers to send connection requests, but the capability stays in the code so it can be revived (ADR-0001). A new `connect_mode` config setting defaults to `manual`; while it's manual, the `send` and `sync` commands are hidden from help and refuse to run with a clear message pointing at the setting. Setting it to `automated` restores today's behavior exactly.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] `connect_mode` is a validated config setting with values `manual` and `automated`, defaulting to `manual`; the example config documents it
- [x] With `manual`, `send` and `sync` don't appear in CLI help and exit with a non-zero code and a message explaining how to re-enable them
- [x] With `automated`, `send` and `sync` behave as before; the existing send, brake, cap, and crash-resume tests still pass (run with `automated`)
- [x] A test covers the refusal under `manual`
- [x] README's daily-use and scheduling sections note that sending is switched off by default

## Comments

**Implemented (2026-11-21).** `Config.connect_mode` (`Literal["manual","automated"]`, default `manual`). The guard is `refuse_if_manual` in `commands/common.py`, called at the top of `send.run` and `sync.run`, so direct callers are covered too, not just the CLI. It exits with `EXIT_REFUSED` (7) and logs an `info` activity row. `cli.peek_connect_mode` reads config.yaml before parsing so help can drop `send`/`sync` while they still parse. Tests: `tests/test_connect_mode.py`. `test_send.py` and `test_logs.py` opt in through the new `conftest.use_config` helper. `scripts/demo_cli.py` opts in too. Full suite passes (147).
