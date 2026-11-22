"""Local dashboard: FastAPI on 127.0.0.1:8765.

Hardening:
- Binds to 127.0.0.1 only. Requests whose Host header isn't 127.0.0.1:8765 or
  localhost:8765 get 403 (blocks DNS rebinding).
- A random 32-byte token is generated at startup and handed to the page in the
  URL fragment (never sent to the server, never logged). Every /api request must
  carry it in the X-Linkreach-Token header, or it gets 403.
- No CORS headers. State changes are POST only.
- CSP: default-src 'self', plus a per-launch nonce for the page's one inline
  <script> and <style> block. The page renders all data with textContent.

The Review, Outbox, and Follow-ups tabs (and their endpoints) are gone with the old bulk
flow's drafting path; a later phase adds a Job form.
"""

from __future__ import annotations

import secrets
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from linkreach import clock, logsetup
from linkreach.config import Inputs
from linkreach.db import DB, STATUSES, TransitionError
from linkreach.safety import brake_status, cap_status, overall_acceptance

PORT = 8765
HOST = "127.0.0.1"
LAUNCH_CODE_SECONDS = 120
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
TOKEN_HEADER = "x-linkreach-token"
INDEX = Path(__file__).with_name("index.html")
FUNNEL = ["collected", "drafted", "approved", "sent", "accepted", "replied", "meeting"]
# statuses that imply a person passed through each funnel stage
_STAGE_REACHED = {
    "collected": set(STATUSES),
    "drafted": {"drafted", "approved", "sent", "failed", "accepted", "followed_up", "replied", "meeting", "referral"},
    "approved": {"approved", "sent", "failed", "accepted", "followed_up", "replied", "meeting", "referral"},
    "sent": {"sent", "accepted", "followed_up", "replied", "meeting", "referral"},
    "accepted": {"accepted", "followed_up", "replied", "meeting", "referral"},
    "replied": {"replied", "meeting", "referral"},
    "meeting": {"meeting", "referral"},
}
LINKEDIN_COMMANDS = ["job", "send", "sync", "doctor"]
ALL_COMMANDS = ["job", "send", "sync", "doctor"]

log = logsetup.get("dashboard")


class StatusBody(BaseModel):
    status: str = Field(max_length=32)


class NotesBody(BaseModel):
    my_notes: str = Field(max_length=5000)


LIVE_SECONDS = 180  # a run with no activity for this long is treated as finished


def _row(r: Any) -> dict[str, Any]:
    return {k: r[k] for k in r.keys()}


def create_app(inputs: Inputs, db_path: Path, token: str | None = None) -> FastAPI:
    token = token or secrets.token_urlsafe(32)  # 32 random bytes
    logsetup.add_secret(token)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    # One-time code for opening the browser. On Windows the default-browser handoff can drop the
    # "#token=..." fragment, so `serve` opens /open?code=... and the server redirects to the
    # fragment URL itself. The code works once, expires after LAUNCH_CODE_SECONDS, and is not the token.
    app.state.launch_code = secrets.token_urlsafe(24)
    app.state.launch_expires = time.monotonic() + LAUNCH_CODE_SECONDS
    logsetup.add_secret(app.state.launch_code)
    cfg = inputs.config

    def db() -> DB:
        return DB.open(db_path)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").lower()
        if host not in ALLOWED_HOSTS:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not supplied or not secrets.compare_digest(supplied, token):
                return JSONResponse({"error": "missing or bad token"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.lower() not in {f"http://{h}" for h in ALLOWED_HOSTS}:
                return JSONResponse({"error": "forbidden origin"}, status_code=403)
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cache-Control", "no-store")
        if "content-security-policy" not in response.headers:
            response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/open")
    def open_with_code(code: str = "") -> Response:
        live = app.state.launch_code and time.monotonic() < app.state.launch_expires
        if not live or not code or not secrets.compare_digest(code, app.state.launch_code):
            return HTMLResponse(
                "<!doctype html><title>linkreach</title><p>This link has expired or was already used. "
                "Close the dashboard window and open the dashboard again from the linkreach menu.</p>",
                status_code=403,
            )
        app.state.launch_code = None  # single use
        return RedirectResponse(f"/#token={token}", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        nonce = secrets.token_urlsafe(16)
        html = INDEX.read_text(encoding="utf-8").replace("__NONCE__", nonce)
        csp = (
            f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'nonce-{nonce}'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return HTMLResponse(html, headers={"Content-Security-Policy": csp})

    # ---------- reads ----------
    @app.get("/api/summary")
    def summary() -> dict[str, Any]:
        d = db()
        try:
            caps = cap_status(d, cfg)
            brake = brake_status(d, cfg)
            sent, acc, rate = overall_acceptance(d)
            last_runs: dict[str, Any] = {}
            for cmd in ALL_COMMANDS:
                r = d.conn.execute(
                    "SELECT timestamp, detail FROM activity_log WHERE command = ? AND event = 'run' ORDER BY id DESC LIMIT 1",
                    (cmd,),
                ).fetchone()
                last_runs[cmd] = {"at": r["timestamp"], "detail": r["detail"]} if r else None
            last_send = d.conn.execute(
                "SELECT detail FROM activity_log WHERE command = 'send' AND event = 'run' AND detail LIKE 'start:%' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            overridden = bool(last_send and "override_brake" in last_send["detail"])
            marks = ", ".join("?" for _ in LINKEDIN_COMMANDS)
            last_end = d.conn.execute(
                f"SELECT timestamp, command, detail FROM activity_log WHERE event = 'run' AND detail LIKE 'end:%' "  # nosec B608
                f"AND command IN ({marks}) ORDER BY id DESC LIMIT 1",
                LINKEDIN_COMMANDS,
            ).fetchone()
            banner = None
            if last_end and last_end["detail"].startswith("end:stopped"):
                banner = {
                    "at": last_end["timestamp"],
                    "command": last_end["command"],
                    "reason": last_end["detail"].removeprefix("end:stopped:"),
                }
            # "How the tool is acting right now": open runs and the latest event.
            running = []
            recent_cutoff = clock.iso(clock.now() - timedelta(seconds=LIVE_SECONDS))
            for cmd in ALL_COMMANDS:
                r = last_runs.get(cmd)
                if r and r["detail"].startswith("start"):
                    act = d.conn.execute(
                        "SELECT MAX(timestamp) FROM activity_log WHERE command = ?", (cmd,)
                    ).fetchone()[0]
                    if act and act >= recent_cutoff:
                        running.append(cmd)
            le = d.conn.execute(
                "SELECT a.timestamp, a.command, a.event, a.detail, p.name FROM activity_log a "
                "LEFT JOIN people p ON p.id = a.person_id WHERE a.event != 'run' ORDER BY a.id DESC LIMIT 1"
            ).fetchone()
            last_event = _row(le) if le else None
            counts = {
                s: n for s, n in d.conn.execute("SELECT status, COUNT(*) FROM people GROUP BY status")
            }
            return {
                "running": running,
                "last_event": last_event,
                "counts": counts,
                "sent_today": caps.requests_today,
                "daily_cap": caps.requests_cap,
                "sent_week": caps.requests_week,
                "weekly_cap": caps.week_cap,
                "views_today": caps.views_today,
                "views_cap": caps.views_cap,
                "acceptance": {"sent": sent, "accepted": acc, "rate": rate},
                "brake": {
                    "status": brake.label(overridden),
                    "sample": brake.sample,
                    "accepted": brake.accepted,
                    "rate": brake.rate,
                    "min_sample": brake.min_sample,
                    "min_rate": brake.min_rate,
                },
                "last_runs": last_runs,
                "banner": banner,
                "statuses": STATUSES,
                "today": clock.local_now().date().isoformat(),
            }
        finally:
            d.close()

    @app.get("/api/people")
    def people() -> list[dict[str, Any]]:
        d = db()
        try:
            cols = (
                "id, name, title, company, profile_url, bucket, is_alumni, status, sent_at, "
                "accepted_at, follow_up_date, my_notes, collected_at"
            )
            return [_row(r) for r in d.conn.execute(f"SELECT {cols} FROM people ORDER BY id DESC")]  # nosec B608
        finally:
            d.close()

    @app.get("/api/people/{person_id}")
    def person(person_id: int) -> dict[str, Any]:
        d = db()
        try:
            r = d.get(person_id)
            if r is None:
                raise HTTPException(404, "not found")
            return {"person": _row(r), "history": [_row(h) for h in d.history(person_id)]}
        finally:
            d.close()

    @app.get("/api/companies")
    def companies() -> list[dict[str, Any]]:
        """Every company in the database (from Jobs, or people saved by the old flow)."""
        d = db()
        try:
            out = []
            names = sorted({r[0] for r in d.conn.execute("SELECT DISTINCT company FROM people")}, key=str.lower)
            for name in names:
                rows = d.conn.execute("SELECT status, sent_at, accepted_at FROM people WHERE company = ? COLLATE NOCASE", (name,)).fetchall()
                sent = [r for r in rows if r["sent_at"]]
                acc = [r for r in sent if r["accepted_at"] or r["status"] in _STAGE_REACHED["accepted"]]
                last = max((r["sent_at"] for r in sent), default=None)
                out.append(
                    {
                        "company": name,
                        "people": len(rows),
                        "sent": len(sent),
                        "accepted": len(acc),
                        "rate": (len(acc) / len(sent)) if sent else None,
                        "last_contact": last,
                        "flag": len(sent) >= 5 and not acc,
                    }
                )
            return out
        finally:
            d.close()

    @app.get("/api/insights")
    def insights() -> dict[str, Any]:
        d = db()
        try:
            rows = d.conn.execute("SELECT bucket, is_alumni, status, sent_at, accepted_at FROM people").fetchall()
            by_bucket: dict[str, dict[str, int]] = {}
            by_week: dict[str, dict[str, int]] = {}
            for r in rows:
                if not r["sent_at"]:
                    continue
                accepted = bool(r["accepted_at"]) or r["status"] in _STAGE_REACHED["accepted"]
                keys = [r["bucket"] or "unknown"] + (["alumni"] if r["is_alumni"] else [])
                for k in keys:
                    b = by_bucket.setdefault(k, {"sent": 0, "accepted": 0})
                    b["sent"] += 1
                    b["accepted"] += int(accepted)
                sent_day = clock.parse(r["sent_at"]).astimezone().date()
                week_start = (sent_day - timedelta(days=sent_day.weekday())).isoformat()
                w = by_week.setdefault(week_start, {"sent": 0, "accepted": 0})
                w["sent"] += 1
                w["accepted"] += int(accepted)
            funnel = {stage: sum(1 for r in rows if r["status"] in _STAGE_REACHED[stage]) for stage in FUNNEL}
            return {
                "by_bucket": [{"bucket": k, **v} for k, v in sorted(by_bucket.items())],
                "by_week": [{"week": k, **v} for k, v in sorted(by_week.items())],
                "funnel": [{"stage": s, "count": funnel[s]} for s in FUNNEL],
            }
        finally:
            d.close()

    @app.get("/api/activity")
    def activity(limit: int = 500) -> list[dict[str, Any]]:
        d = db()
        try:
            return [_row(r) for r in d.activity(min(max(limit, 1), 5000))]
        finally:
            d.close()

    # ---------- writes (POST only, token required by middleware) ----------
    @app.post("/api/people/{person_id}/status")
    def set_status(person_id: int, body: StatusBody) -> dict[str, Any]:
        if body.status not in STATUSES:
            raise HTTPException(400, "unknown status")
        d = db()
        try:
            if d.get(person_id) is None:
                raise HTTPException(404, "not found")
            try:
                d.set_status(person_id, body.status, source="dashboard", manual=True, follow_up_days=cfg.follow_up_delay_days)
            except TransitionError as exc:
                raise HTTPException(400, str(exc)) from exc
            return {"person": _row(d.get(person_id))}
        finally:
            d.close()

    @app.post("/api/people/{person_id}/notes")
    def set_notes(person_id: int, body: NotesBody) -> dict[str, Any]:
        d = db()
        try:
            if d.get(person_id) is None:
                raise HTTPException(404, "not found")
            d.update_fields(person_id, my_notes=body.my_notes)
            return {"ok": True}
        finally:
            d.close()

    return app


class PortInUse(RuntimeError):
    pass


def port_free(host: str = HOST, port: int = PORT) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def serve(inputs: Inputs, db_path: Path, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    import uvicorn

    # Check first: otherwise the browser opens on whatever else holds the port (another dashboard,
    # or the demo) and that page rejects this run's token.
    if not port_free():
        raise PortInUse(
            f"Port {PORT} is already in use, so another dashboard (or the demo) is still running. "
            "Close that window, or stop it with Ctrl-C, then open the dashboard again."
        )
    app = create_app(inputs, db_path)
    url = f"http://{HOST}:{PORT}/#token={app.state.token}"
    launch = f"http://{HOST}:{PORT}/open?code={app.state.launch_code}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(launch)).start()
    where = " (opening in your browser)" if open_browser else ""
    print(f"linkreach dashboard on http://{HOST}:{PORT}/{where}. Close this window or press Ctrl-C to stop.")
    print("If the page says it has no access token, paste this link into your browser:")
    print(url)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", access_log=False, server_header=False)
