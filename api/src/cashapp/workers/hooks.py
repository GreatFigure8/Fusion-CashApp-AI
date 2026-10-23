"""Extension point for the 30 s health tick. Later stories append their checks here."""

from datetime import datetime
from typing import Protocol

from cashapp.pipeline.roles import Container
from cashapp.services.notifications.sources import NotificationSourcesHook


class HealthTickHook(Protocol):
    """A housekeeping check run on every health tick. It reads local state only."""

    async def on_tick(self, container: Container, now: datetime) -> None: ...


# Hook modules must not import cashapp.workers.host. Append an instance to this literal.
HEALTH_TICK_HOOKS: list[HealthTickHook] = [NotificationSourcesHook()]
