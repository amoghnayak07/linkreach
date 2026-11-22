"""Gmail drafts: linkreach saves each Email draft to the user's Gmail Drafts folder.

linkreach only ever creates drafts. It asks Google for the `gmail.compose` scope only and
has no code that calls Gmail's send endpoint; the user reviews and sends each draft.

- `GmailDrafts` is the one-operation interface the Job flow uses, injected through the
  command context (tests use a fake that records drafts).
- `ApiGmail` is the real implementation: Gmail's REST API over HTTPS, with the user's own
  OAuth desktop client and a refresh token kept in the OS keychain.
- `login` runs Google's installed-app sign-in (loopback redirect + PKCE) for `gmail-login`.

Standard library only, so no new dependency enters the lock files. The refresh token and
access tokens are never written to disk, printed, or logged (they're also registered with
the log redaction filter).
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Protocol

from linkreach import credentials, logsetup

log = logsetup.get("gmail")

SCOPE = "https://www.googleapis.com/auth/gmail.compose"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105 - a public endpoint, not a password
DRAFTS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
KEYCHAIN_NAME = "GMAIL_OAUTH"
HTTP_TIMEOUT = 30
LOGIN_TIMEOUT = 300


class GmailError(Exception):
    """A Gmail call failed. The message never holds draft content or tokens."""


class GmailNotSignedIn(GmailError):
    pass


class GmailDrafts(Protocol):
    def create_draft(self, to: str, subject: str, body: str) -> str:
        """Save a draft to the user's Drafts folder and return its id. Never sends."""
        ...


# ---------------------------------------------------------------- keychain


@dataclass
class StoredAuth:
    client_id: str
    client_secret: str
    refresh_token: str

    def to_json(self) -> str:
        return json.dumps({"client_id": self.client_id, "client_secret": self.client_secret, "refresh_token": self.refresh_token})


def load_auth() -> StoredAuth | None:
    """The stored sign-in, or None when `gmail-login` hasn't been run (or the keychain is
    unavailable)."""
    try:
        import keyring

        raw = keyring.get_password(credentials.SERVICE, KEYCHAIN_NAME)
    except Exception:  # no backend, locked keychain, etc.
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        auth = StoredAuth(str(data["client_id"]), str(data.get("client_secret", "")), str(data["refresh_token"]))
    except (ValueError, KeyError, TypeError):
        return None
    if not auth.client_id or not auth.refresh_token:
        return None
    logsetup.add_secret(auth.refresh_token)
    logsetup.add_secret(auth.client_secret)
    return auth


def store_auth(auth: StoredAuth) -> None:
    import keyring

    keyring.set_password(credentials.SERVICE, KEYCHAIN_NAME, auth.to_json())


def has_token() -> bool:
    return load_auth() is not None


# ---------------------------------------------------------------- HTTP


def _https_only(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise GmailError("refusing a non-HTTPS Google URL")


def _post(url: str, data: bytes, headers: dict[str, str]) -> dict[str, Any]:
    _https_only(url)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # nosec B310 - https only, fixed Google hosts
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        # Google's error bodies don't echo request content; keep only the short reason code.
        reason = ""
        try:
            err = json.loads(exc.read().decode("utf-8") or "{}")
            e = err.get("error")
            reason = e if isinstance(e, str) else str((e or {}).get("status", ""))
        except Exception:
            pass
        raise GmailError(f"Google returned HTTP {exc.code}" + (f" ({reason})" if reason else "")) from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise GmailError(f"couldn't reach Google ({type(exc).__name__})") from None
    except ValueError:
        raise GmailError("Google sent a reply linkreach couldn't read") from None


def _post_form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("ascii")
    return _post(url, body, {"Content-Type": "application/x-www-form-urlencoded"})


# ---------------------------------------------------------------- drafts


def build_raw(to: str, subject: str, body: str) -> str:
    """The base64url RFC 2822 message Gmail's drafts endpoint takes."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class ApiGmail:
    """Gmail REST API with the compose scope. Has exactly one operation: create a draft."""

    def __init__(self, auth: StoredAuth, post_form: Callable[[str, dict[str, str]], dict[str, Any]] = _post_form,
                 post: Callable[[str, bytes, dict[str, str]], dict[str, Any]] = _post):
        self.auth = auth
        self._post_form = post_form
        self._post = post
        self._access: str | None = None
        self._expires = 0.0

    def _access_token(self) -> str:
        if self._access and time.monotonic() < self._expires - 60:
            return self._access
        fields = {"client_id": self.auth.client_id, "refresh_token": self.auth.refresh_token, "grant_type": "refresh_token"}
        if self.auth.client_secret:
            fields["client_secret"] = self.auth.client_secret
        try:
            data = self._post_form(TOKEN_URL, fields)
        except GmailError as exc:
            if "invalid_grant" in str(exc):
                raise GmailNotSignedIn("the Gmail sign-in expired or was revoked; run `linkreach gmail-login` again") from None
            raise
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise GmailError("Google didn't return an access token")
        logsetup.add_secret(token)
        self._access = token
        self._expires = time.monotonic() + float(data.get("expires_in") or 3600)
        return token

    def create_draft(self, to: str, subject: str, body: str) -> str:
        payload = json.dumps({"message": {"raw": build_raw(to, subject, body)}}).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"}
        data = self._post(DRAFTS_URL, payload, headers)
        draft_id = data.get("id")
        if not isinstance(draft_id, str) or not draft_id:
            raise GmailError("Gmail didn't return a draft id")
        return draft_id


def make_client() -> ApiGmail:
    auth = load_auth()
    if auth is None:
        raise GmailNotSignedIn("no Gmail sign-in is stored; run `linkreach gmail-login` first")
    return ApiGmail(auth)


# ---------------------------------------------------------------- sign-in


class LoginError(Exception):
    pass


def read_client_file(path: Path) -> tuple[str, str]:
    """(client_id, client_secret) from the JSON Google Cloud gives for a Desktop app client."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LoginError(f"can't read {path} ({exc.strerror or type(exc).__name__})") from None
    except ValueError:
        raise LoginError(f"{path} isn't a JSON file") from None
    if not isinstance(data, dict):
        raise LoginError(f"{path} isn't an OAuth client file")
    if "installed" not in data:
        kind = next(iter(data), "unknown")
        raise LoginError(f"{path} is a '{kind}' client; create an OAuth client of type 'Desktop app' instead")
    inst = data["installed"]
    client_id = str(inst.get("client_id") or "")
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise LoginError(f"{path} has no Google OAuth client_id")
    return client_id, str(inst.get("client_secret") or "")


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


class _Callback(http.server.BaseHTTPRequestHandler):
    # Browsers open spare connections that never send a request; without a read timeout one
    # of those would block the real redirect queued behind it.
    timeout = 3

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if "code" not in query and "error" not in query:
            self.send_response(404)
            self.end_headers()
            return
        self.server.result = {k: v[0] for k, v in query.items()}  # type: ignore[attr-defined]
        ok = "code" in query
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        msg = "linkreach: Gmail sign-in done. You can close this tab." if ok else "linkreach: Gmail sign-in was cancelled."
        self.wfile.write(msg.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # the query holds the auth code: never log it
        pass


class _LoopbackServer(http.server.HTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # an idle or dropped browser connection: ignore it quietly, no traceback


def login(client_file: Path, open_browser: Callable[[str], Any], timeout: float = LOGIN_TIMEOUT,
          post_form: Callable[[str, dict[str, str]], dict[str, Any]] = _post_form) -> StoredAuth:
    """Installed-app sign-in: open Google's consent page, catch the redirect on a loopback
    port, exchange the code (with PKCE), check that only the compose scope was granted,
    and store the refresh token in the keychain. Returns the stored sign-in."""
    client_id, client_secret = read_client_file(client_file)
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)

    server = _LoopbackServer(("127.0.0.1", 0), _Callback)
    server.result = {}  # type: ignore[attr-defined]
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_address[1]}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    try:
        open_browser(url)
        deadline = time.monotonic() + timeout
        while not server.result and time.monotonic() < deadline:  # type: ignore[attr-defined]
            try:
                server.handle_request()
            except (socket.timeout, OSError):
                continue
        result: dict[str, str] = server.result  # type: ignore[attr-defined]
    finally:
        server.server_close()

    if not result:
        raise LoginError("no answer from Google's sign-in page in time; run `linkreach gmail-login` again")
    if result.get("state") != state:
        raise LoginError("the sign-in answer didn't match this request; run `linkreach gmail-login` again")
    if "error" in result:
        raise LoginError(f"Google sign-in didn't complete ({result['error'][:60]})")
    fields = {
        "client_id": client_id,
        "code": result.get("code", ""),
        "code_verifier": verifier,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }
    if client_secret:
        fields["client_secret"] = client_secret
    try:
        data = post_form(TOKEN_URL, fields)
    except GmailError as exc:
        raise LoginError(f"couldn't finish the sign-in: {exc}") from None
    refresh = data.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise LoginError("Google didn't return a refresh token; remove linkreach's access at myaccount.google.com/permissions and try again")
    granted = set(str(data.get("scope") or "").split())
    if granted and granted != {SCOPE}:
        raise LoginError("Google granted other scopes than gmail.compose; linkreach only accepts the compose scope, so nothing was stored")
    logsetup.add_secret(refresh)
    auth = StoredAuth(client_id, client_secret, refresh)
    store_auth(auth)
    return auth
