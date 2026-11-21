"""ADR-0001: `connect_mode` switches the automated send path off by default."""

from __future__ import annotations

import pytest

from linkreach.cli import main
from linkreach.commands.common import EXIT_CONFIG, EXIT_REFUSED

from tests.conftest import base_session, freeze_weekday_morning, use_config, write_inputs
from tests.helpers import add_approved, profile_for


def no_browser(cfg):
    raise AssertionError("a refused command must not open a browser")


def help_text(capsys) -> str:
    with pytest.raises(SystemExit):
        main(["--help"])
    return capsys.readouterr().out


def test_default_is_manual(env):
    assert env.inputs.config.connect_mode == "manual"


def test_invalid_connect_mode_refuses_to_start(env, capsys):
    write_inputs(env.inputs_dir, {"connect_mode": "sometimes"})
    assert main(["list"]) == EXIT_CONFIG
    assert "connect_mode" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["send", "sync"])
def test_manual_refuses_send_and_sync(env, capsys, command):
    freeze_weekday_morning()
    pid = add_approved(env, "jane")
    if command == "sync":
        env.db.set_status(pid, "sent")

    code = main([command], ctx_overrides={"session_factory": no_browser})

    assert code == EXIT_REFUSED
    out = capsys.readouterr().out
    assert "switched off" in out and "connect_mode: automated" in out
    assert env.db.get(pid)["status"] == ("approved" if command == "send" else "sent")


def test_manual_hides_send_and_sync_from_help(env, capsys):
    out = help_text(capsys)
    assert "collect" in out and "doctor" in out
    assert "send approved connection requests" not in out
    assert "mark accepted connections" not in out


def test_automated_lists_send_and_sync_in_help(env, capsys):
    use_config(env)
    out = help_text(capsys)
    assert "send approved connection requests" in out
    assert "mark accepted connections" in out


def test_automated_send_runs_through_cli(env):
    use_config(env)
    freeze_weekday_morning()
    pid = add_approved(env, "jane")
    s = base_session()
    page = profile_for(s, "jane")

    code = main(["send"], ctx_overrides={"session_factory": lambda cfg: s, "sleep": lambda _: None, "input_fn": lambda _: ""})

    assert code == 0
    assert page.send_clicks == 1 and env.db.get(pid)["status"] == "sent"
