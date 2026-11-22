from __future__ import annotations

import pytest
import yaml

from linkreach.browser import ProfileGuardError, default_chrome_dirs, guard_profile_dir, host_allowed
from linkreach.cli import main
from linkreach.config import ConfigError, load_inputs

from tests.conftest import write_inputs


def test_valid_inputs_load(env):
    assert env.inputs.config.caps.daily_requests == 20
    assert not (env.inputs_dir / "companies.csv").exists()  # config.yaml is the only input file


def test_all_errors_reported_at_once(env):
    d = env.inputs_dir
    cfg = yaml.safe_load((d / "config.yaml").read_text())
    del cfg["resume_url"]
    cfg["caps"]["daily_requests"] = 50  # above the hard ceiling
    cfg["doctor_profile_url"] = "not-a-profile"
    (d / "config.yaml").write_text(yaml.safe_dump(cfg))
    with pytest.raises(ConfigError) as exc:
        load_inputs(d)
    text = "\n".join(exc.value.problems)
    assert "resume_url" in text
    assert "daily_requests" in text
    assert "doctor_profile_url" in text
    assert len(exc.value.problems) >= 3


OLD_FLOW_SETTINGS = {
    "buckets": {"recruiter": {"keywords": ["technical recruiter"], "angle": "ask about open reqs"}},
    "per_company_limit": 6,
    "combine_keywords": True,
    "alumni_angle": "Lead with Northeastern",
    "exclude_title_keywords": ["intern"],
    "followup_max_words": 150,
    "templates": {"note": "Hi {first_name}, {opener} {tie_line}"},
}


def test_old_bulk_flow_settings_are_named_and_rejected(env):
    write_inputs(env.inputs_dir, OLD_FLOW_SETTINGS)
    with pytest.raises(ConfigError) as exc:
        load_inputs(env.inputs_dir)
    problems = exc.value.problems
    assert len(problems) == len(OLD_FLOW_SETTINGS)  # one clear line each, no pydantic noise
    for key in OLD_FLOW_SETTINGS:
        assert any(p.startswith(f"config.yaml: {key}: removed setting") and "delete it" in p for p in problems), key


def test_old_config_stops_the_cli_with_the_removed_keys(env, capsys):
    write_inputs(env.inputs_dir, {"buckets": OLD_FLOW_SETTINGS["buckets"], "templates": OLD_FLOW_SETTINGS["templates"]})
    assert main(["list"]) == 2
    out = capsys.readouterr().out
    assert "buckets: removed setting" in out and "templates: removed setting" in out and "style.md" in out


def test_leftover_csvs_are_ignored(env):
    (env.inputs_dir / "companies.csv").write_text("company_name\nnot,even,valid\n")
    (env.inputs_dir / "jobs.csv").write_text("garbage")
    assert load_inputs(env.inputs_dir).config.pick_target == 5


def test_default_chrome_profile_refused(env):
    default = default_chrome_dirs()[0]
    write_inputs(env.inputs_dir, {"chrome_profile_dir": str(default)})
    with pytest.raises(ConfigError) as exc:
        load_inputs(env.inputs_dir)
    assert "default browser profile" in "\n".join(exc.value.problems)
    # a profile folder inside it is refused too
    with pytest.raises(ProfileGuardError):
        guard_profile_dir(default / "Default")


def test_cli_refuses_to_start_on_default_profile(env, capsys):
    write_inputs(env.inputs_dir, {"chrome_profile_dir": str(default_chrome_dirs()[0])})
    code = main(["list"])
    assert code == 2
    assert "refuses to start" in capsys.readouterr().out


def test_dedicated_profile_allowed(env, tmp_path):
    guard_profile_dir(tmp_path / ".linkreach" / "chrome-profile")


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://www.linkedin.com/in/x/", True),
        ("https://static.licdn.com/a.js", True),
        ("https://media.licdn.com/img.png", True),
        ("https://linkedin.com/feed/", True),
        ("https://evil.example/", False),
        ("https://linkedin.com.evil.example/", False),
        ("https://notlinkedin.com/", False),
        ("javascript:alert(1)", False),
        ("about:blank", True),
    ],
)
def test_domain_allowlist(url, ok):
    assert host_allowed(url) is ok
