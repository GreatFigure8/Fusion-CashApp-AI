"""Poller heartbeats: when each of the two pollers last finished a cycle.

This only writes state. It is not a loop and not a third poller: the intake cycle hook and the
receipt watcher call it once per cycle they already run.
"""

import logging
from datetime import datetime
from typing import Final

from cashapp.data.repositories.poller_heartbeat import PollerHeartbeatRepository
from cashapp.data.uow import UnitOfWork
from cashapp.pipeline.roles import Container

logger = logging.getLogger(__name__)

POLLER_NAMES: Final = ("intake-poller", "receipt-watcher")
STATUS_OK: Final = "ok"
STATUS_DEGRADED: Final = "degraded"


async def record_poller_heartbeat(
    uow: UnitOfWork, name: str, at: datetime, *, status: str = STATUS_OK
) -> None:
    """Upsert the poller's row inside the caller's unit of work. Flushes, never commits."""
    await uow.repo(PollerHeartbeatRepository).upsert(name, at=at, status=status)


class PollerHeartbeatHook:
    """The intake poller's ``CycleHook`` that stamps its heartbeat after each cycle."""

    def __init__(self, name: str) -> None:
        self._name = name

    async def on_cycle(self, container: Container, now: datetime) -> None:
        async with container.uow_factory() as uow:
            await record_poller_heartbeat(uow, self._name, now)
            await uow.commit()
