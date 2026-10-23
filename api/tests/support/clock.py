"""A controllable clock for tests; satisfies ``cashapp.domain.clock.Clock``."""

from datetime import UTC, datetime, timedelta


class FrozenClock:
    def __init__(self, at: datetime = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **delta: float) -> None:
        """Move forward by ``timedelta(**delta)``, for example ``advance(minutes=5)``."""
        self._at = self._at + timedelta(**delta)

    def set(self, at: datetime) -> None:
        self._at = at
