from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from linkreach.dashboard.server import INDEX, create_app

from tests.helpers import add_approved, add_drafted, url

TOKEN = "t" * 43


@pytest.fixture
def client(env):
    app = create_app(env.inputs, env.db.path, token=TOKEN)
    return TestClient(app, base_url="http://127.0.0.1:8765")


H = {"X-Linkreach-Token": TOKEN}


def test_no_token_is_403(client):
    assert client.get("/api/people").status_code == 403
    assert client.get("/api/people", headers={"X-Linkreach-Token": "wrong"}).status_code == 403
    assert client.post("/api/people/1/status", json={"status": "dead"}).status_code == 403


def test_foreign_host_is_403(client):
    r = client.get("/api/people", headers={**H, "Host": "evil.example:8765"})
    assert r.status_code == 403
    r = client.get("/", headers={"Host": "attacker.test"})
    assert r.status_code == 403
    assert client.get("/api/people", headers={**H, "Host": "localhost:8765"}).status_code == 200


def test_foreign_origin_is_403(client):
    assert client.get("/api/people", headers={**H, "Origin": "https://evil.example"}).status_code == 403


def test_no_cors_headers(client):
    r = client.get("/api/summary", headers={**H, "Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert not any(k.lower().startswith("access-control-") for k in r.headers)
    r = client.options("/api/summary", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert not any(k.lower().startswith("access-control-") for k in r.headers)


def test_state_changes_are_post_only(client, env):
    pid = add_drafted(env, "x")
    assert client.get(f"/api/people/{pid}/status", headers=H).status_code == 405
    assert client.put(f"/api/people/{pid}/status", headers=H, json={"status": "dead"}).status_code == 405


def test_csp_and_security_headers(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert csp.startswith("default-src 'self'")
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in r.text and f'<style nonce="{nonce}">' in r.text
    assert r.headers["x-frame-options"] == "DENY"
    api = client.get("/api/summary", headers=H)
    assert api.headers["content-security-policy"].startswith("default-src 'self'")


def test_page_never_uses_innerhtml():
    src = INDEX.read_text(encoding="utf-8")
    script = src[src.index("<script"):]
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script.replace("No innerHTML anywhere", ""), sink


def test_script_name_returned_as_plain_data(client, env):
    env.db.add_person(name="<script>alert(1)</script>", company="Microsoft", profile_url=url("xss"))
    r = client.get("/api/people", headers=H)
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()[0]["name"] == "<script>alert(1)</script>"


def test_status_change_writes_history_and_cli_sees_it(client, env, capsys):
    from linkreach.commands import misc

    pid = add_approved(env, "jane")
    env.db.set_status(pid, "sent")
    r = client.post(f"/api/people/{pid}/status", headers=H, json={"status": "accepted"})
    assert r.status_code == 200, r.text
    hist = env.db.history(pid)
    assert (hist[-1]["old_status"], hist[-1]["new_status"], hist[-1]["source"]) == ("sent", "accepted", "dashboard")
    misc.list_people(env.ctx(), "accepted")  # `linkreach list --status accepted`
    assert "1 people" in capsys.readouterr().out
    assert env.db.get(pid)["follow_up_date"]


def test_dashboard_cannot_approve(client, env):
    pid = add_drafted(env, "y")
    r = client.post(f"/api/people/{pid}/status", headers=H, json={"status": "approved"})
    assert r.status_code == 400
    assert env.db.get(pid)["status"] == "drafted"


REMOVED_ENDPOINTS = [
    ("get", "/api/review"),
    ("get", "/api/outbox"),
    ("get", "/api/followups"),
    ("post", "/api/validate"),
    ("post", "/api/people/{pid}/approve"),
    ("post", "/api/people/{pid}/decline"),
    ("post", "/api/people/{pid}/unapprove"),
    ("post", "/api/people/{pid}/draft"),
    ("post", "/api/people/{pid}/redraft"),
    ("post", "/api/people/{pid}/followup/done"),
    ("post", "/api/people/{pid}/followup/snooze"),
    ("post", "/api/people/{pid}/followup/regenerate"),
]


def test_review_outbox_and_followup_endpoints_are_gone(client, env):
    pid = add_drafted(env, "gone")
    for method, path in REMOVED_ENDPOINTS:
        r = getattr(client, method)(path.format(pid=pid), headers=H, **({"json": {}} if method == "post" else {}))
        assert r.status_code in (404, 405), (path, r.status_code)
    assert env.db.get(pid)["status"] == "drafted"


def test_page_has_no_review_outbox_or_followups_tab(client):
    page = client.get("/").text
    tabs = re.findall(r'data-tab="([a-z]+)"', page)
    assert tabs == ["people", "companies", "insights", "activity"]
    for gone in ("tab-review", "tab-outbox", "tab-followups", "/api/review", "/api/outbox", "/api/followups"):
        assert gone not in page, gone


def test_summary_companies_insights_activity(client, env):
    pid = add_approved(env, "h")
    env.db.set_status(pid, "sent")
    env.db.log("job", "run", None, "end:stopped:captcha")
    s = client.get("/api/summary", headers=H).json()
    assert s["daily_cap"] == 20 and s["weekly_cap"] == 80
    assert s["brake"]["status"] == "off"
    assert s["banner"] == {"at": s["banner"]["at"], "command": "job", "reason": "captcha"}
    assert set(s["last_runs"]) == {"job", "send", "sync", "doctor"}
    comps = client.get("/api/companies", headers=H).json()
    assert comps[0]["company"] == "Microsoft" and comps[0]["people"] == 1 and comps[0]["sent"] == 1
    ins = client.get("/api/insights", headers=H).json()
    assert ins["funnel"][0] == {"stage": "collected", "count": 1}
    assert ins["by_bucket"][0] == {"bucket": "unknown", "sent": 1, "accepted": 0}
    acts = client.get("/api/activity", headers=H).json()
    assert acts[0]["detail"] == "end:stopped:captcha"


def test_company_flag_after_five_sends_no_accepts(client, env):
    for i in range(5):
        pid = add_approved(env, f"z{i}")
        env.db.set_status(pid, "sent")
    comps = {c["company"]: c for c in client.get("/api/companies", headers=H).json()}
    assert comps["Microsoft"]["flag"] is True
