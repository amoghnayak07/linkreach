from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from linkreach import clock, credentials, gmail, logsetup
from linkreach.commands.common import Ctx
from linkreach.config import Inputs, load_inputs
from linkreach.db import DB

from tests.fakes import FakeClaude, FakeGmail, FakeSession, feed_page, job_responder

EXAMPLES = Path(__file__).resolve().parent.parent / "linkreach" / "examples"
FAKE_KEY = "sk-ant-api03-TESTKEYabcdefghijklmnopqrstuvwxyz0123456789"
DOCTOR_URL = "https://www.linkedin.com/in/doctor-test/"


@dataclass
class Env:
    root: Path
    inputs_dir: Path
    home: Path
    inputs: Inputs
    db: DB

    def ctx(self, session: FakeSession | None = None, answers: list[str] | None = None, **kw: Any) -> Ctx:
        queue = list(answers or [])
        sess = session
        calls = {"n": 0}

        def factory(cfg):
            calls["n"] += 1
            if sess is None:
                raise AssertionError("this test must not open a browser")
            return sess

        def input_fn(prompt: str) -> str:
            return queue.pop(0) if queue else ""

        ctx = Ctx(inputs=self.inputs, db=self.db, session_factory=factory, sleep=lambda s: None, input_fn=input_fn)
        ctx.api_check = kw.pop("api_check", lambda model: (True, "fake key ok"))
        ctx.claude_client = kw.pop("claude_client", FakeClaude(job_responder()))  # never the real API in tests
        ctx.gmail = kw.pop("gmail", FakeGmail())  # never real Gmail; gmail=None means "no sign-in stored"
        ctx.factory_calls = calls  # type: ignore[attr-defined]
        for k, v in kw.items():
            setattr(ctx, k, v)
        return ctx

    def reload(self) -> None:
        self.inputs = load_inputs(self.inputs_dir)


def write_inputs(d: Path, overrides: dict | None = None) -> None:
    cfg = yaml.safe_load((EXAMPLES / "config.example.yaml").read_text(encoding="utf-8"))
    cfg["resume_url"] = "https://example.com/naveen-resume.pdf"
    cfg["doctor_profile_url"] = DOCTOR_URL
    cfg["chrome_profile_dir"] = str(d.parent / "home" / "chrome-profile")
    cfg["auto_window"] = {"days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "start": "00:00", "end": "23:59"}
    for k, v in (overrides or {}).items():
        cfg[k] = v
    (d / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def use_config(env: Env, overrides: dict | None = None, automated: bool = True) -> None:
    """Rewrite config.yaml with overrides and reload. Defaults to `connect_mode: automated`,
    which the dormant send/sync path needs to run (ADR-0001)."""
    merged = {"connect_mode": "automated" if automated else "manual", **(overrides or {})}
    write_inputs(env.inputs_dir, merged)
    env.reload()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    home = tmp_path / "home"
    inputs_dir = tmp_path / "inputs"
    home.mkdir()
    inputs_dir.mkdir()
    monkeypatch.setenv("LINKREACH_HOME", str(home))
    monkeypatch.setenv("LINKREACH_INPUTS", str(inputs_dir))
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(credentials, "_from_keyring", lambda: None)
    monkeypatch.setattr(gmail, "load_auth", lambda: None)  # never the real keychain's Gmail sign-in
    credentials.reset_cache()
    logsetup.reset()
    logsetup.setup()
    clock.reset()
    write_inputs(inputs_dir)
    inputs = load_inputs(inputs_dir)
    db = DB.open(home / "linkreach.db")
    e = Env(root=tmp_path, inputs_dir=inputs_dir, home=home, inputs=inputs, db=db)
    yield e
    db.close()
    logsetup.reset()
    clock.reset()
    credentials.reset_cache()


def base_session() -> FakeSession:
    from tests.fakes import ProfilePage

    s = FakeSession()
    s.add(feed_page())
    s.add(ProfilePage(DOCTOR_URL, name="Doctor Test", headline="Test profile", about="About text"))
    return s


def freeze_weekday_morning() -> None:
    tz = datetime.now().astimezone().tzinfo
    clock.freeze(datetime(2026, 11, 18, 10, 0, tzinfo=tz))  # a Wednesday
