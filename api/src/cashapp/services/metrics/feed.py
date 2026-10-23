"""A process-wide, single-flight view of new history rows for the ``/metrics/stream`` connections.

N open streams share one read per tick instead of one each. This is a view of the database, not a
poller of an external source: nothing is emitted to the bus and no schedule is involved. History
is written by worker processes, so the outbox signal cannot be shared (it is in-process and the
relay consumes it).
"""

import asyncio
import time
from collections.abc import Callable
from typing import Final

from cashapp.data.repositories.metrics import HistoryActivityRow, MetricsQueryRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.metrics import MetricsWindow
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.flow_query import STREAM_TICK_SECONDS
from cashapp.services.metrics.models import ProgressSummary
from cashapp.services.metrics.service import MetricsService

BUFFER_ROWS: Final = 1000
FETCH_ROWS: Final = 500
SUMMARY_MAX_AGE_SECONDS: Final = 30.0


class MetricsChangeFeed:
    def __init__(
        self,
        *,
        tick_seconds: float = STREAM_TICK_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tick = tick_seconds
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._summary_lock = asyncio.Lock()
        self._rows: list[HistoryActivityRow] = []
        self._base_id: int | None = None  # the buffer holds relevant rows with id > _base_id
        self._latest_id = 0
        self._fetched_at: float | None = None
        self._summaries: dict[MetricsWindow, tuple[int, float, ProgressSummary]] = {}

    async def _refresh(self, uow_factory: UowFactory) -> None:
        async with self._lock:
            now = self._monotonic()
            if self._fetched_at is not None and now - self._fetched_at < self._tick:
                return
            async with uow_factory() as uow:  # read-only: leaving the block rolls back
                repo = MetricsQueryRepository(uow.session)
                latest = await repo.latest_history_id()
                if self._base_id is None:
                    self._base_id = latest
                    self._latest_id = latest
                elif latest > self._latest_id:
                    cursor = self._latest_id
                    while cursor < latest:
                        batch = await repo.activity(FETCH_ROWS, after_id=cursor)
                        if not batch:
                            break
                        self._rows.extend(batch)
                        cursor = batch[-1].id
                        if len(batch) < FETCH_ROWS:
                            break
                    self._latest_id = latest
            if len(self._rows) > BUFFER_ROWS:
                dropped = self._rows[: len(self._rows) - BUFFER_ROWS]
                self._rows = self._rows[len(dropped) :]
                self._base_id = dropped[-1].id
            self._fetched_at = now

    async def latest_id(self, uow_factory: UowFactory) -> int:
        """The newest history id, read at most once per tick for the whole process."""
        await self._refresh(uow_factory)
        return self._latest_id

    async def since(
        self, uow_factory: UowFactory, after_id: int, limit: int
    ) -> list[HistoryActivityRow]:
        """Relevant history rows with id > ``after_id``, ascending, at most ``limit``."""
        await self._refresh(uow_factory)
        base = self._base_id if self._base_id is not None else 0
        if after_id < base:  # older than the shared buffer: read directly
            async with uow_factory() as uow:
                return await MetricsQueryRepository(uow.session).activity(limit, after_id)
        return [row for row in self._rows if row.id > after_id][:limit]

    async def summary(
        self,
        uow_factory: UowFactory,
        *,
        clock: Clock,
        config: RuntimeConfig | ConfigSnapshot,
        window: MetricsWindow,
    ) -> ProgressSummary:
        """The summary for ``window``, recomputed once per new history id (or every 30 s)."""
        latest = await self.latest_id(uow_factory)
        async with self._summary_lock:
            cached = self._summaries.get(window)
            now = self._monotonic()
            if cached and cached[0] == latest and now - cached[1] < SUMMARY_MAX_AGE_SECONDS:
                return cached[2]
            async with uow_factory() as uow:
                summary = await MetricsService(uow, clock=clock, config=config).summary(window)
            self._summaries[window] = (latest, now, summary)
            return summary
