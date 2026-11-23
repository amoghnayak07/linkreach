# 12: Remove the CLI, SQLite and send code

**What to build:** Delete everything the web app replaces, so the web app is the only interface (ADR-0001 and ADR-0005).

**Blocked by:** 05, 11

**Status:** ready-for-agent

- [ ] `linkreach/cli.py`, `linkreach/commands/` and the `linkreach` console entry point deleted; the FastAPI app gets its own start command
- [ ] SQLite code in `db.py` and the YAML config removed
- [ ] `send`, `sync`, `connect_mode`, the connect selectors, the acceptance brake and request caps deleted
- [ ] The old `linkreach/dashboard/` page and the Activity tab removed, with any useful bits moved to the new app
- [ ] Tests for removed code deleted; remaining tests pass
- [ ] README rewritten for the web app: prerequisites (Docker, Node, Python 3.11+, Ollama + `ollama pull`), `.env`, Profile file, Setup page, a Run
