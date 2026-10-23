"""The backlog publish throttle: the outbox relay's only brake on historical remittances.

Live rows (priority at least ``PRIORITY_LIVE``) are admitted at once with no database access.
Backlog rows are admitted per batch at the batch's rate (a token bucket), only when no live row is
waiting, never for a paused batch. The buckets are in-process: run one relay per environment.
"""

import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from cashapp.data.repositories.backlog import BacklogBatchRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.backlog import TERMINAL_BATCH_STATUSES, BacklogStatus
from cashapp.domain.clock import Clock
from cashapp.domain.work_item import PRIORITY_LIVE
from cashapp.pipeline.relay import OutboxRow
from cashapp.pipeline.roles import Container
from cashapp.services.config import RuntimeConfig

logger = logging.getLogger(__name__)

_ITEM_TTL: Final = timedelta(seconds=10)


class TokenBucket:
    """Smooth pacing: ``rate_per_min / 60`` tokens a second, holding at most ``capacity``."""

    def __init__(self, rate_per_min: int, *, clock: Clock, capacity: float = 1.0) -> None:
        self._rate_per_second = max(rate_per_min, 1) / 60.0
        self._capacity = capacity
        self._clock = clock
        self._tokens = capacity
        self._updated = clock.now()

    def try_take(self) -> bool:
        now = self._clock.now()
        elapsed = max((now - self._updated).total_seconds(), 0.0)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate_per_second)
        self._updated = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


@dataclass(frozen=True, slots=True)
class _BatchInfo:
    id: int
    status: BacklogStatus
    rate_per_min: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class _ItemBatch:
    batch_id: int | None
    expires_at: datetime


class BacklogThrottle:
    """Satisfies the relay's ``PublishThrottle`` protocol."""

    def __init__(
        self,
        uow_factory: UowFactory,
        config: RuntimeConfig,
        clock: Clock,
        *,
        live_check_seconds: float = 1.0,
        batch_cache_seconds: float = 2.0,
        item_cache_size: int = 10_000,
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config
        self._clock = clock
        self._live_check = timedelta(seconds=live_check_seconds)
        self._batch_ttl = timedelta(seconds=batch_cache_seconds)
        self._item_cache_size = item_cache_size
        self._items: OrderedDict[int, _ItemBatch] = OrderedDict()
        self._batches: dict[int, _BatchInfo] = {}
        self._buckets: dict[int, tuple[int, TokenBucket]] = {}
        self._live_seen_at: datetime | None = None
        self._live_checked_at: datetime | None = None
        self._live_result = False

    async def admit(self, row: OutboxRow) -> bool:
        now = self._clock.now()
        if row.priority >= PRIORITY_LIVE:
            self._live_seen_at = now
            return True
        if row.work_item_id is None:
            return True
        try:
            batch = await self._batch_for_item(row.work_item_id, now)
            if batch is None:
                return True  # low priority but not a batch item
            if batch.status in TERMINAL_BATCH_STATUSES:
                return True  # drain; the runners' claim makes it a no-op
            if batch.status == BacklogStatus.PAUSED:
                return False
            if await self._live_waiting(now):
                return False
        except Exception as exc:
            # Hold the backlog row rather than fail the relay cycle that also carries live rows.
            logger.warning("backlog throttle lookup failed: error=%s", type(exc).__name__)
            return False
        return self._bucket(batch).try_take()

    def _bucket(self, batch: _BatchInfo) -> TokenBucket:
        existing = self._buckets.get(batch.id)
        if existing is not None and existing[0] == batch.rate_per_min:
            return existing[1]
        bucket = TokenBucket(batch.rate_per_min, clock=self._clock)
        self._buckets[batch.id] = (batch.rate_per_min, bucket)
        return bucket

    async def _batch_for_item(self, item_id: int, now: datetime) -> _BatchInfo | None:
        cached = self._items.get(item_id)
        if cached is not None and cached.expires_at > now:
            self._items.move_to_end(item_id)
            if cached.batch_id is None:
                return None
            info = self._batches.get(cached.batch_id)
            if info is not None and info.expires_at > now:
                return info
            return await self._load_batch(cached.batch_id, now)

        async with self._uow_factory() as uow:
            batch = await uow.repo(BacklogBatchRepository).batch_for_item(item_id)
        self._remember_item(item_id, batch.id if batch is not None else None, now)
        if batch is None:
            return None
        rate = await self._effective_rate(batch.rate_limit_per_min)
        return self._remember_batch(batch.id, batch.status, rate, now)

    async def _load_batch(self, batch_id: int, now: datetime) -> _BatchInfo | None:
        async with self._uow_factory() as uow:
            batch = await uow.repo(BacklogBatchRepository).get(batch_id)
        if batch is None:
            return None
        rate = await self._effective_rate(batch.rate_limit_per_min)
        return self._remember_batch(batch.id, batch.status, rate, now)

    async def _effective_rate(self, batch_rate: int | None) -> int:
        if batch_rate:
            return batch_rate
        return (await self._config.snapshot()).backlog().rate_limit_per_minute

    def _remember_item(self, item_id: int, batch_id: int | None, now: datetime) -> None:
        self._items[item_id] = _ItemBatch(batch_id, now + _ITEM_TTL)
        self._items.move_to_end(item_id)
        while len(self._items) > self._item_cache_size:
            self._items.popitem(last=False)

    def _remember_batch(
        self, batch_id: int, status: BacklogStatus, rate: int, now: datetime
    ) -> _BatchInfo:
        info = _BatchInfo(batch_id, status, rate, now + self._batch_ttl)
        self._batches[batch_id] = info
        return info

    async def _live_waiting(self, now: datetime) -> bool:
        if self._live_seen_at is not None and now - self._live_seen_at < self._live_check:
            return True
        if self._live_checked_at is not None and now - self._live_checked_at < self._live_check:
            return self._live_result
        async with self._uow_factory() as uow:
            waiting = await uow.repo(BacklogBatchRepository).live_outbox_waiting(
                now=now, min_priority=PRIORITY_LIVE
            )
        self._live_checked_at = now
        self._live_result = waiting
        return waiting


def build_backlog_throttle(container: Container) -> BacklogThrottle:
    """Registered with the worker container as the relay's ``PublishThrottle``."""
    return BacklogThrottle(container.uow_factory, container.config, container.clock)
