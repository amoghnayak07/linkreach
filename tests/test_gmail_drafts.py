"""Gmail drafts (ticket 07): through the `job` command with a fake Gmail client and an Email
finder that returns emails, plus the real client's request shape and `gmail-login`, with
every Google endpoint faked."""

from __future__ import annotations

import base64
import email
import json
import logging
import threading
import urllib.parse
import urllib.request
from email import policy
from pathlib import Path

import pytest

from linkreach import gmail, logsetup, paths
from linkreach.commands import job, misc, redraft
from linkreach.commands.common import EXIT_CONFIG, EXIT_OK
from linkreach.emailfinder import FinderResult

from tests.fakes import GOOD_EMAIL, FakeClaude, FakeGmail, job_responder
from tests.helpers import url
from tests.test_job import answers, picks, session_with, write_style

EMAILS = {url("jane-doe"): "jane@contoso.com", url("raj-k"): "raj@contoso.com"}


class MapFinder:
    """Email finder fake: an email per profile URL, nothing for the rest."""

    def __init__(self, emails: dict[str, str]):
        self.emails = emails

    def find(self, li, profile):
        e = self.emails.get(li.s.url)  # the open profile page
        return FinderResult(email=e, source="test", reason="" if e else "not found")


@pytest.fixture(autouse=True)
def supplied_only(env):
    from tests.conftest import use_config

    use_config(env, {"pick_target": 1}, automated=False)
    write_style()


def run_job(env, slugs, mail=None, finder=None, **kw):
    s = session_with(*slugs)
    mail = mail if mail is not None else FakeGmail()
    ctx = env.ctx(s, answers=answers([url(x) for x in slugs]), gmail=mail, email_finder=finder or MapFinder(EMAILS), **kw)
    return job.run(ctx), ctx, mail


# ---------------------------------------------------------------- through `job`


def test_pick_with_an_email_gets_a_gmail_draft(env, capsys):
    code, ctx, mail = run_job(env, ["jane-doe"])
    assert code == EXIT_OK
    assert mail.drafts == [("jane@contoso.com", GOOD_EMAIL["subject"], GOOD_EMAIL["body"])]
    p = picks(env)[0]
    assert (p["status"], p["email"], p["gmail_draft_id"]) == ("drafted", "jane@contoso.com", "draft-1")
    assert [(h["old_status"], h["new_status"]) for h in env.db.pick_history(p["id"])] == [(None, "picked"), ("picked", "drafted")]
    out = capsys.readouterr().out
    assert "Gmail draft saved" in out
    assert GOOD_EMAIL["connection_note"] in out  # the note is still printed
    assert "drafts 1, Gmail drafts 1," in out


def test_pick_without_an_email_gets_no_gmail_draft(env):
    code, ctx, mail = run_job(env, ["jane-doe", "raj-k"], finder=MapFinder({url("raj-k"): "raj@contoso.com"}))
    assert code == EXIT_OK
    assert [d[0] for d in mail.drafts] == ["raj@contoso.com"]
    rows = {r["profile_url"]: r for r in picks(env)}
    assert rows[url("jane-doe")]["status"] == "no_email"
    assert rows[url("jane-doe")]["gmail_draft_id"] is None
    assert rows[url("raj-k")]["status"] == "drafted"


def test_needs_detail_pick_gets_no_gmail_draft(env):
    bad = dict(GOOD_EMAIL, subject="x" * 90)
    code, ctx, mail = run_job(env, ["jane-doe"], claude_client=FakeClaude(job_responder(email=bad)))
    assert code == EXIT_OK
    assert mail.drafts == []
    p = picks(env)[0]
    assert p["status"] == "needs_detail"
    assert p["email"] == "jane@contoso.com"  # kept, so a redraft needs no new Reveal


def test_gmail_failure_for_one_pick_is_logged_and_the_run_continues(env, capsys):
    mail = FakeGmail(fail_for={"jane@contoso.com"})
    code, ctx, _ = run_job(env, ["jane-doe", "raj-k"], mail=mail)
    assert code == EXIT_OK
    rows = {r["profile_url"]: r for r in picks(env)}
    jane, raj = rows[url("jane-doe")], rows[url("raj-k")]
    assert raj["status"] == "drafted" and raj["gmail_draft_id"] == "draft-1"
    # Jane's draft is saved and waits for Gmail: status unchanged, no draft id.
    assert jane["status"] == "picked" and jane["gmail_draft_id"] is None
    assert (jane["email"], jane["email_subject"], jane["connection_note"]) == ("jane@contoso.com", GOOD_EMAIL["subject"], GOOD_EMAIL["connection_note"])
    # Logged without content.
    rows_log = [r["detail"] for r in env.db.activity() if "gmail draft failed" in (r["detail"] or "")]
    assert rows_log == [f"pick {jane['id']}: gmail draft failed (GmailError)"]
    out = capsys.readouterr().out
    assert "Gmail failed" in out and "linkreach redraft" in out
    assert "Gmail drafts 1, needs detail 0, failures 1," in out
    assert out.count(GOOD_EMAIL["connection_note"]) == 2  # Jane's note is still printed

    # Retryable: `redraft` creates the missing Gmail draft without asking or opening a browser.
    retry = FakeGmail()
    ctx2 = env.ctx(session=None, gmail=retry)
    assert redraft.run(ctx2) == EXIT_OK
    assert retry.drafts == [("jane@contoso.com", GOOD_EMAIL["subject"], GOOD_EMAIL["body"])]
    jane = env.db.get_pick(jane["id"])
    assert (jane["status"], jane["gmail_draft_id"]) == ("drafted", "draft-1")
    assert ctx2.factory_calls["n"] == 0


def test_job_refuses_without_a_gmail_sign_in(env, capsys):
    fake = FakeClaude(job_responder())
    ctx = env.ctx(session=None, answers=answers([url("jane-doe")]), gmail=None, claude_client=fake)
    assert job.run(ctx) == EXIT_CONFIG
    assert fake.calls == [] and ctx.factory_calls["n"] == 0
    assert env.db.get_job(1) is None
    out = capsys.readouterr().out
    assert "no Gmail sign-in is stored" in out and "gmail-login" in out


def test_found_emails_and_drafts_stay_out_of_logs(env):
    run_job(env, ["jane-doe"], mail=FakeGmail(fail_for={"jane@contoso.com"}))
    for h in logging.getLogger("linkreach").handlers:
        h.flush()
    text = "\n".join(f.read_text(encoding="utf-8") for f in paths.logs_dir().glob("linkreach.log*"))
    assert "gmail draft failed" in text
    assert "jane@contoso.com" not in text and GOOD_EMAIL["subject"] not in text


# ---------------------------------------------------------------- the real client, faked HTTP

AUTH = gmail.StoredAuth("123-abc.apps.googleusercontent.com", "client-secret-xyz", "1//refresh-token-secret")


def test_api_client_creates_a_draft_with_the_compose_flow():
    forms, posts = [], []

    def post_form(u, fields):
        forms.append((u, fields))
        return {"access_token": "ya29.access-token-value", "expires_in": 3600}

    def post(u, data, headers):
        posts.append((u, json.loads(data), headers))
        return {"id": "r-123", "message": {"id": "m1"}}

    client = gmail.ApiGmail(AUTH, post_form=post_form, post=post)
    assert client.create_draft("jane@contoso.com", "Hello there", "Hi Jane,\n\nBody text.") == "r-123"
    assert client.create_draft("raj@contoso.com", "Second", "Body") == "r-123"

    assert len(forms) == 1  # the access token is reused
    u, fields = forms[0]
    assert u == gmail.TOKEN_URL and fields["grant_type"] == "refresh_token" and fields["refresh_token"] == AUTH.refresh_token
    u, payload, headers = posts[0]
    assert u == "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
    assert headers["Authorization"] == "Bearer ya29.access-token-value"
    msg = email.message_from_bytes(base64.urlsafe_b64decode(payload["message"]["raw"]), policy=policy.default)
    assert msg["To"] == "jane@contoso.com" and msg["Subject"] == "Hello there"
    assert msg.get_content().strip() == "Hi Jane,\n\nBody text."


def test_revoked_sign_in_reads_as_not_signed_in():
    def post_form(u, fields):
        raise gmail.GmailError("Google returned HTTP 400 (invalid_grant)")

    client = gmail.ApiGmail(AUTH, post_form=post_form, post=lambda *a: {})
    with pytest.raises(gmail.GmailNotSignedIn):
        client.create_draft("a@b.co", "s", "b")


def test_nothing_in_linkreach_calls_a_gmail_send_endpoint():
    src = Path(gmail.__file__).resolve().parent
    for f in src.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "messages/send" not in text and "drafts/send" not in text, f
    assert gmail.SCOPE == "https://www.googleapis.com/auth/gmail.compose"


# ---------------------------------------------------------------- gmail-login


def client_file(tmp_path: Path, kind: str = "installed") -> Path:
    p = tmp_path / "client.json"
    p.write_text(json.dumps({kind: {"client_id": AUTH.client_id, "client_secret": AUTH.client_secret}}), encoding="utf-8")
    return p


def browser_that_consents(params: dict | None = None):
    """Stands in for the user's browser: reads the consent URL, then hits the loopback
    redirect with a code and the same state (or `params` to override)."""
    seen = {}

    def open_browser(auth_url: str) -> None:
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(auth_url).query).items()}
        seen.update(q)
        answer = {"code": "4/auth-code", "state": q["state"], **(params or {})}
        target = q["redirect_uri"] + "?" + urllib.parse.urlencode(answer)

        def hit():
            urllib.request.urlopen(target, timeout=5).read()  # noqa: S310 - loopback test server

        threading.Thread(target=hit, daemon=True).start()

    return open_browser, seen


def test_gmail_login_stores_the_refresh_token_in_the_keychain(tmp_path, monkeypatch, env):
    stored = []
    monkeypatch.setattr(gmail, "store_auth", stored.append)
    forms = []

    def post_form(u, fields):
        forms.append(fields)
        return {"refresh_token": AUTH.refresh_token, "access_token": "ya29.x", "scope": gmail.SCOPE}

    open_browser, seen = browser_that_consents()
    auth = gmail.login(client_file(tmp_path), open_browser, timeout=10, post_form=post_form)

    assert stored == [auth] and auth.refresh_token == AUTH.refresh_token
    assert seen["scope"] == gmail.SCOPE and seen["access_type"] == "offline" and seen["code_challenge_method"] == "S256"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert forms[0]["code"] == "4/auth-code" and forms[0]["code_verifier"]
    # The token is never written to disk in the data folder, and is scrubbed from logs.
    for f in paths.home().rglob("*"):
        if f.is_file() and f.suffix != ".db":
            assert AUTH.refresh_token not in f.read_text(encoding="utf-8", errors="ignore")
    assert AUTH.refresh_token not in logsetup.redact(f"token {AUTH.refresh_token}")


def test_gmail_login_refuses_broader_scopes(tmp_path, monkeypatch, env):
    stored = []
    monkeypatch.setattr(gmail, "store_auth", stored.append)

    def post_form(u, fields):
        return {"refresh_token": "1//r", "scope": gmail.SCOPE + " https://mail.google.com/"}

    open_browser, _ = browser_that_consents()
    with pytest.raises(gmail.LoginError, match="compose scope"):
        gmail.login(client_file(tmp_path), open_browser, timeout=10, post_form=post_form)
    assert stored == []


def test_gmail_login_rejects_a_mismatched_state(tmp_path, monkeypatch, env):
    monkeypatch.setattr(gmail, "store_auth", lambda a: pytest.fail("must not store"))
    open_browser, _ = browser_that_consents({"state": "forged"})
    with pytest.raises(gmail.LoginError, match="didn't match"):
        gmail.login(client_file(tmp_path), open_browser, timeout=10, post_form=lambda u, f: pytest.fail("no exchange"))


def test_gmail_login_command_explains_a_wrong_client_type(tmp_path, env, capsys):
    assert misc.gmail_login(client_file(tmp_path, kind="web"), open_browser=lambda u: None) == 1
    assert "Desktop app" in capsys.readouterr().out
