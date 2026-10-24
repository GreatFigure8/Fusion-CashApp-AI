"""``EventBus`` on the database: the queue is the ``BUS_MESSAGE`` table.

Consumers claim due messages with ``SELECT … FOR UPDATE SKIP LOCKED`` and a lease, so any number
of worker processes share a topic without a broker. ``commit()`` marks a message consumed; a
message whose lease ran out unconsumed (a crash) is claimed again, which is harmless because every
handler checks the item's stage and status first. A consumer is woken at once by a publish in the
same process, and sees one from another process within ``idle_seconds``: it waits on its own queue
and checks nothing outside the database, so it is not a poller in the sense of the two exceptions.
"""

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import timedelta
from typing import Final

from cashapp.data.models.bus_message import BusMessage
from cashapp.data.repositories.bus_messages import BusMessageRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import PRIORITY_LIVE
from cashapp.pipeline.bus import Delivery
from cashapp.pipeline.events import TopicNamer
from cashapp.pipeline.relay import OutboxSignal

logger = logging.getLogger(__name__)

PRIORITY_HEADER: Final = "priority"
_signal = OutboxSignal()


class DbEventBus:
    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        namer: TopicNamer,
        clock: Clock | None = None,
        lease_seconds: float = 600.0,
        idle_seconds: float = 2.0,
        batch_size: int = 20,
    ) -> None:
        self._uow_factory = uow_factory
        self._namer = namer
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._lease = timedelta(seconds=lease_seconds)
        self._idle_seconds = idle_seconds
        self._batch_size = batch_size

    async def publish(
        self,
        topic: str,
        key: str | None,
        payload: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        stored = dict(headers or {})
        try:
            priority = int(stored.get(PRIORITY_HEADER, PRIORITY_LIVE))
        except ValueError:
            priority = PRIORITY_LIVE
        async with self._uow_factory() as uow:
            await uow.repo(BusMessageRepository).add(
                BusMessage(
                    topic=topic,
                    msg_key=key,
                    body=payload.decode("utf-8"),
                    headers=stored,
                    priority=priority,
                    created_at=self._clock.now(),
                    attempts=0,
                )
            )
            await uow.commit()
        _signal.notify()

    def _delivery(self, row: BusMessage) -> Delivery:
        message_id = row.id

        async def commit() -> None:
            async with self._uow_factory() as uow:
                await uow.repo(BusMessageRepository).mark_consumed(message_id, at=self._clock.now())
                await uow.commit()

        return Delivery(
            row.topic,
            0,
            message_id,
            row.msg_key,
            row.body.encode("utf-8"),
            {str(k): str(v) for k, v in row.headers.items()},
            commit,
        )

    async def _claim(self, topics: Sequence[str]) -> list[Delivery]:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            rows = await uow.repo(BusMessageRepository).claim(
                topics, now=now, lease_until=now + self._lease, limit=self._batch_size
            )
            deliveries = [self._delivery(row) for row in rows]
            await uow.commit()
        return deliveries

    async def _release(self, deliveries: Sequence[Delivery]) -> None:
        ids = [d.offset for d in deliveries if not d.committed]
        if not ids:
            return
        async with self._uow_factory() as uow:
            await uow.repo(BusMessageRepository).release(ids)
            await uow.commit()

    async def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]:
        """Yield messages as they become due. ``group`` is accepted for the interface and unused:
        one environment is one database, so there is exactly one group."""
        ready: deque[Delivery] = deque()
        try:
            while True:
                if not ready:
                    ready.extend(await self._claim(topics))
                if ready:
                    yield ready.popleft()
                    continue
                await _signal.wait(self._idle_seconds)
        finally:
            # Messages claimed but never handed out go back at once; shielded because this runs
            # when the consumer is cancelled. A crash instead leaves them to the lease timeout.
            with contextlib.suppress(Exception):
                await asyncio.shield(self._release(list(ready)))

    async def consumer_lag(self, topic: str) -> int:
        async with self._uow_factory() as uow:
            return await uow.repo(BusMessageRepository).pending_count(topic)

    async def dlq_depth(self, stage: Stage) -> int:
        return await self.consumer_lag(self._namer.for_stage(stage, "dlq"))

    async def close(self) -> None:
        _signal.notify()
