from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Account:
    key: str
    alias: str
    provider: str


@dataclass(frozen=True)
class Usage:
    status: str
    session_percent: float | None
    session_reset_minutes: int | None
    weekly_percent: float | None
    weekly_reset_minutes: int | None


class Provider(Protocol):
    def fetch(self, account: Account) -> Usage:
        """Return usage for one configured account without exposing credentials."""
