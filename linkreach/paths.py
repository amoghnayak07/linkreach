"""Filesystem locations and permission hardening.

Everything private (DB, logs, Chrome profile, temp edit files) lives under
``~/.linkreach`` (override with ``LINKREACH_HOME``). The folder is 700 and files
are 600. On Windows ``chmod`` only toggles the read-only bit, so the README asks
for BitLocker and the folder lives inside your user profile, which Windows
already restricts to your account.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def home() -> Path:
    override = os.environ.get("LINKREACH_HOME")
    base = Path(override).expanduser() if override else Path.home() / ".linkreach"
    return base


def inputs_dir() -> Path:
    """Where config.yaml, companies.csv, and jobs.csv are read from."""
    override = os.environ.get("LINKREACH_INPUTS")
    return Path(override).expanduser() if override else Path.cwd()


STYLE_FILE = "style.md"


def style_path() -> Path:
    """The user's Style file, next to config.yaml (gitignored)."""
    return inputs_dir() / STYLE_FILE


def db_path() -> Path:
    return home() / "linkreach.db"


def logs_dir() -> Path:
    return home() / "logs"


def screenshots_dir() -> Path:
    return logs_dir() / "screenshots"


def tmp_dir() -> Path:
    return home() / "tmp"


def default_chrome_profile() -> Path:
    return home() / "chrome-profile"


def secure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, stat.S_IRWXU)  # 700
    except OSError:
        pass
    return path


def secure_file(path: Path) -> Path:
    if path.exists():
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass
    return path


def ensure_home() -> Path:
    h = secure_dir(home())
    secure_dir(logs_dir())
    secure_dir(screenshots_dir())
    secure_dir(tmp_dir())
    return h
