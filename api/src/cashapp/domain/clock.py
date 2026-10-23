"""Injectable clock. All business code takes a Clock so tests can freeze time."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def utcnow() -> datetime:
    """Wall-clock UTC, used for ORM column defaults."""
    return datetime.now(UTC)
