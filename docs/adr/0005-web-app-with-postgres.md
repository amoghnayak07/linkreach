# A local web app with Postgres replaces the CLI and SQLite

linkreach is a FastAPI server plus a React frontend, both on 127.0.0.1, storing data in Postgres. The CLI and SQLite are removed. A Run takes minutes and the user wants to watch it, and confirming extracted fields or copying Connection notes is easier in a browser than a terminal. Two interfaces would mean two places to keep in sync.

Only Postgres runs in Docker (`docker compose up`). The app runs natively because the Run drives a visible Chrome window with the Dedicated profile and Gmail OAuth opens the local browser, which would both be awkward from a container.

## Consequences

- Runs are background threads in the FastAPI process, one at a time, with per-step state in Postgres and progress pushed over Server-Sent Events. No job queue is needed for a single local user.
- There's no login, but the server binds to 127.0.0.1 and keeps the token header, Host check and CSP, because any website the user visits could otherwise call a localhost API that creates Gmail drafts.
- Per-user settings live in a gitignored `.env`. Personal files (Profile file, Dedicated profile, Google OAuth client) live under `~/.linkreach/`. The Gmail token lives in the OS keychain. Each fork runs its own instance with nothing shared.
- Existing SQLite data isn't migrated.
