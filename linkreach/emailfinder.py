"""Email finder: turns a Pick's open LinkedIn profile into a work email, or nothing.

The Job pipeline calls `find` once per Pick while that Pick's profile is the open page.
Implementations must not navigate away (ADR-0002: code decides every page view) and must
treat their own failures as soft: return no email with a reason instead of raising.
The Apollo and ContactOut finders come later (tickets 08 and 09); until then the default
is `NoFinder`, so every drafted Pick ends `no_email`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from linkreach.linkedin import LinkedIn, Profile


@dataclass
class FinderResult:
    email: str | None
    source: str  # which finder answered, e.g. "none", "apollo"
    reason: str = ""  # why there is no email, for the summary; never contains the email

    @property
    def found(self) -> bool:
        return bool(self.email)


class EmailFinder(Protocol):
    def find(self, li: LinkedIn, profile: Profile) -> FinderResult: ...


class NoFinder:
    """Looks nothing up."""

    def find(self, li: LinkedIn, profile: Profile) -> FinderResult:
        return FinderResult(email=None, source="none", reason="no email finder set up yet")
