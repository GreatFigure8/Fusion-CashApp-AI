"""Window logic: at most one message per kind per window. Pure, no I/O.

The first event of a kind opens a window that ends ``window_seconds`` later. A critical event
sends at once, with whatever its kind has buffered, unless that kind already sent inside the
last window; then it joins the buffer like any other event.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from cashapp.domain.notifications import NotifyEvent, NotifySeverity

_RANK = {
    NotifySeverity.INFO.value: 0,
    NotifySeverity.WARNING.value: 1,
    NotifySeverity.CRITICAL.value: 2,
}


@dataclass(frozen=True, slots=True)
class Batch:
    kind: str
    events: tuple[NotifyEvent, ...]
    severity: str  # the highest severity in the batch


@dataclass(slots=True)
class _Window:
    opened_at: datetime
    events: list[NotifyEvent] = field(default_factory=lambda: [])


def _max_severity(events: list[NotifyEvent]) -> str:
    return max((e.severity.value for e in events), key=lambda s: _RANK.get(s, 0))


class NotificationBatcher:
    def __init__(self, *, window_seconds: int) -> None:
        self.window_seconds = window_seconds
        self._open: dict[str, _Window] = {}
        self._last_sent_at: dict[str, datetime] = {}

    def _window(self) -> timedelta:
        return timedelta(seconds=self.window_seconds)

    def _pop(self, kind: str, now: datetime) -> Batch:
        window = self._open.pop(kind)
        self._last_sent_at[kind] = now
        return Batch(kind, tuple(window.events), _max_severity(window.events))

    def add(self, event: NotifyEvent, now: datetime) -> Batch | None:
        """Buffer ``event``; return a batch to send now when a critical event leads the edge."""
        kind = event.kind.value
        window = self._open.get(kind)
        if window is None:
            window = _Window(opened_at=now)
            self._open[kind] = window
        window.events.append(event)
        if event.severity == NotifySeverity.CRITICAL:
            last = self._last_sent_at.get(kind)
            if last is None or now - last >= self._window():
                return self._pop(kind, now)
        return None

    def due(self, now: datetime) -> list[Batch]:
        """Every window that has elapsed, oldest first."""
        elapsed = sorted(
            (w.opened_at, kind) for kind, w in self._open.items() if now >= self._deadline(w)
        )
        return [self._pop(kind, now) for _, kind in elapsed]

    def _deadline(self, window: _Window) -> datetime:
        return window.opened_at + self._window()

    def next_deadline(self) -> datetime | None:
        if not self._open:
            return None
        return min(self._deadline(w) for w in self._open.values())

    def drain_all(self) -> list[Batch]:
        """Every open window regardless of its deadline (shutdown)."""
        batches: list[Batch] = []
        for kind in sorted(self._open, key=lambda k: self._open[k].opened_at):
            window = self._open.pop(kind)
            batches.append(Batch(kind, tuple(window.events), _max_severity(window.events)))
        return batches
