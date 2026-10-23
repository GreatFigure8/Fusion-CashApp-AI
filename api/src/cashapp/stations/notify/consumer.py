"""Consumes the notify topic and sends batched messages.

A plain Runnable, not a ``StageRunner``: a notify event has no work item to claim. Events of one
kind are held per window (``NotificationBatcher``); the offsets of a batch's deliveries are
committed only after its NOTIFICATION_LOG rows are committed. The flush timer only drains events
that have already arrived; it never queries anything external.
"""

import asyncio
import contextlib
import logging
from collections import OrderedDict
from datetime import datetime
from uuid import UUID

from pydantic import ValidationError

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.notifications import NotifyEvent
from cashapp.pipeline.bus import Delivery, EventBus, close_stream, next_or_stop
from cashapp.pipeline.events import TopicNamer
from cashapp.pipeline.roles import Container, RoleState, RoleStatus
from cashapp.services.config import RuntimeConfig
from cashapp.services.notifications.batcher import Batch, NotificationBatcher
from cashapp.services.notifications.channel import build_channels
from cashapp.services.notifications.dispatcher import NotificationDispatcher
from cashapp.services.notify import notify_topic

logger = logging.getLogger(__name__)

ROLE_NAME = "notify"
SEEN_LIMIT = 10_000
MAX_BACKOFF_SECONDS = 30
MAX_IDLE_WAIT_SECONDS = 60.0


class NotifyConsumer:
    """Satisfies the pipeline ``Runnable`` protocol."""

    def __init__(
        self,
        *,
        bus: EventBus,
        group: str,
        uow_factory: UowFactory,
        config: RuntimeConfig,
        clock: Clock,
        dispatcher: NotificationDispatcher,
        topic: str | None = None,
    ) -> None:
        self._bus = bus
        self._group = group
        self._uow_factory = uow_factory
        self._config = config
        self._clock = clock
        self._dispatcher = dispatcher
        self._topic = topic or notify_topic()
        self._batcher = NotificationBatcher(window_seconds=0)
        self._pending: dict[str, list[Delivery]] = {}
        self._seen: OrderedDict[UUID, None] = OrderedDict()
        self._changed = asyncio.Event()
        self._status: RoleStatus = "starting"
        self._detail: str | None = None
        self._last_activity_at: datetime | None = None

    @classmethod
    def build(cls, container: Container) -> "NotifyConsumer":
        settings = container.settings
        dispatcher = NotificationDispatcher(
            build_channels(container.runtime), clock=container.clock, env_label=settings.env.upper()
        )
        return cls(
            bus=container.bus,
            group=container.runtime.streaming().consumer_group,
            uow_factory=container.uow_factory,
            config=container.config,
            clock=container.clock,
            dispatcher=dispatcher,
            topic=notify_topic(
                TopicNamer.from_config(container.runtime.streaming(), container.runtime.env)
            ),
        )

    def state(self) -> RoleState:
        return RoleState(
            name=ROLE_NAME,
            status=self._status,
            last_activity_at=self._last_activity_at,
            detail=self._detail,
        )

    async def _refresh_window(self) -> None:
        self._batcher.window_seconds = (await self._config.notifications()).batch_window_seconds

    def _remember(self, event_id: UUID) -> bool:
        """True when the id is new; False for a duplicate seen in this process."""
        if event_id in self._seen:
            self._seen.move_to_end(event_id)
            return False
        self._seen[event_id] = None
        if len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)
        return True

    async def handle_delivery(self, delivery: Delivery) -> None:
        """Parse, dedupe, then buffer the event or send its batch now (a critical leading edge)."""
        try:
            event = NotifyEvent.model_validate_json(delivery.value)
        except ValidationError:
            logger.warning(
                "malformed notify event skipped: partition=%d offset=%d",
                delivery.partition,
                delivery.offset,
            )
            await delivery.commit()
            return
        if not self._remember(event.event_id):
            await delivery.commit()
            return
        await self._refresh_window()
        kind = event.kind.value
        self._pending.setdefault(kind, []).append(delivery)
        batch = self._batcher.add(event, self._clock.now())
        self._changed.set()
        if batch is not None:
            await self._send(batch)

    async def flush_due(self) -> int:
        """Send every window that has elapsed; returns the number of batches sent."""
        await self._refresh_window()
        batches = self._batcher.due(self._clock.now())
        for batch in batches:
            await self._send(batch)
        return len(batches)

    async def _drain(self) -> None:
        for batch in self._batcher.drain_all():
            await self._send(batch)

    async def _send(self, batch: Batch) -> None:
        deliveries = self._pending.pop(batch.kind, [])
        try:
            snapshot = await self._config.snapshot()
            async with self._uow_factory() as uow:
                await self._dispatcher.dispatch(uow, batch, snapshot)
                await uow.commit()
        except Exception as exc:
            # Offsets stay uncommitted, so the events are redelivered after a restart.
            self._status = "degraded"
            self._detail = type(exc).__name__
            logger.warning(
                "notification batch not logged: kind=%s events=%d error=%s",
                batch.kind,
                len(batch.events),
                type(exc).__name__,
            )
            return
        for delivery in deliveries:
            await delivery.commit()
        self._status = "running"
        self._detail = None
        self._last_activity_at = self._clock.now()

    async def _handle_with_retry(self, delivery: Delivery, stop: asyncio.Event) -> bool:
        backoff = 1
        while True:
            try:
                await self.handle_delivery(delivery)
            except Exception as exc:
                self._status = "degraded"
                self._detail = type(exc).__name__
                logger.warning("notify delivery failed; will retry: error=%s", type(exc).__name__)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                if stop.is_set():
                    return False
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            else:
                return True

    async def _read(self, stop: asyncio.Event) -> None:
        stream = self._bus.subscribe([self._topic], self._group)
        try:
            while not stop.is_set():
                delivery = await next_or_stop(stream, stop)
                if delivery is None:
                    break
                if not await self._handle_with_retry(delivery, stop):
                    break
        finally:
            await close_stream(stream)

    def _wait_seconds(self) -> float:
        deadline = self._batcher.next_deadline()
        if deadline is None:
            return MAX_IDLE_WAIT_SECONDS
        remaining = (deadline - self._clock.now()).total_seconds()
        return min(max(remaining, 0.0), MAX_IDLE_WAIT_SECONDS)

    async def _flush_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout=self._wait_seconds())
            self._changed.clear()
            if stop.is_set():
                break
            try:
                await self.flush_due()
            except Exception as exc:
                self._status = "degraded"
                self._detail = type(exc).__name__
                logger.warning("notify flush failed: error=%s", type(exc).__name__)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=1)

    async def run(self, stop: asyncio.Event) -> None:
        self._status = "running"
        reader = asyncio.create_task(self._read(stop))
        flusher = asyncio.create_task(self._flush_loop(stop))
        try:
            await reader
        finally:
            self._status = "stopping"
            stop.set()
            self._changed.set()
            await flusher
            await self._drain()
            self._status = "stopped"
