# 02: Platform skeleton

**What to build:** The empty web app running end to end on localhost. Postgres runs in Docker, the schema is managed by Alembic, and FastAPI serves a React + Tailwind page that shows "Postgres: ok". See the spec's Implementation Decisions (Layout, Serving, Database, Config). The old CLI keeps working until issue 12.

**Blocked by:** none

**Status:** ready-for-agent

- [ ] `docker-compose.yml` with Postgres 17, a named volume, the port bound to 127.0.0.1, and credentials from `.env`
- [ ] `.env.example` committed and `.env` gitignored; settings load through pydantic
- [ ] SQLAlchemy 2.0 (sync) + psycopg 3 models and an initial Alembic migration for Person, Job (including Angle fields), Pick, Run, Run step, status history, activity log and company caches
- [ ] A FastAPI app factory bound to 127.0.0.1, with the token header, Host check and CSP carried over from `linkreach/dashboard/server.py`
- [ ] `web/` with Vite + React + TypeScript + TanStack Query + Tailwind; the dev proxy forwards to FastAPI, including the token; the production build is served by FastAPI
- [ ] A health endpoint and page showing Postgres status
- [ ] Test setup: a `linkreach_test` database, migrations applied once, each test in a rolled-back transaction; Vitest configured in `web/`
- [ ] README section: `docker compose up -d`, migrate, run dev, build
- [ ] Tests: health endpoint; foreign Host and missing token rejected
