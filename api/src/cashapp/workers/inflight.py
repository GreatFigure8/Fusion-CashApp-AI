"""In-flight tracking and per-stage concurrency, applied by decorating the bus roles consume from.

The host cannot see inside the stage consumers' loop, so it hands them this EventBus decorator.
It gates each main-topic delivery on the stage's concurrency limit before the consumer receives
it, and keeps the registry of deliveries that are fetched but not yet committed.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from cashapp.domain.stages import Stage
from cashapp.pipeline.bus import Delivery, EventBus
from cashapp.pipeline.events import StageEvent
from cashapp.services.config import RuntimeConfig

# A raised limit takes effect within this many seconds even when nothing releases a slot.
LIMIT_RECHECK_SECONDS = 1.0
_UNTRACKED_SUFFIXES = (".retry", ".dlq")


@dataclass(frozen=True, slots=True)
class InFlight:
    work_item_id: int
    stage: Stage
    started_at: datetime


class StageLimiter:
    """One counter per stage; the limit is re-read from RuntimeConfig on every acquire."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._in_use: dict[Stage, int] = {}
        self._waiters: dict[Stage, list[asyncio.Future[None]]] = {}

    def in_use(self, stage: Stage) -> int:
        return self._in_use.get(stage, 0)

    async def acquire(self, stage: Stage) -> None:
        while True:
            limit = (await self._config.concurrency()).for_stage(stage)
            if self.in_use(stage) < limit:
                self._in_use[stage] = self.in_use(stage) + 1
                return
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._waiters.setdefault(stage, []).append(waiter)
            try:
                await asyncio.wait_for(asyncio.shield(waiter), timeout=LIMIT_RECHECK_SECONDS)
            except TimeoutError:
                pass
            finally:
                waiting = self._waiters.get(stage, [])
                if waiter in waiting:
                    waiting.remove(waiter)
                if not waiter.done():
                    waiter.cancel()

    def release(self, stage: Stage) -> None:
        count = self.in_use(stage)
        if count > 0:
            self._in_use[stage] = count - 1
        for waiter in self._waiters.get(stage, []):
            if not waiter.done():
                waiter.set_result(None)


@dataclass(slots=True)
class _TrackedDelivery(Delivery):
    """The consumer's view of a delivery: committing it also frees the stage slot."""

    inner: Delivery = field(kw_only=True)
    on_done: Callable[[], None] = field(kw_only=True)

    async def commit(self) -> None:
        await self.inner.commit()
        self.on_done()


class InFlightTrackingBus:
    """EventBus decorator. It is not a third bus implementation."""

    def __init__(
        self,
        inner: EventBus,
        limiter: StageLimiter,
        on_processed: Callable[[Stage], None] | None = None,
    ) -> None:
        self._inner = inner
        self._limiter = limiter
        self._on_processed = on_processed
        self._inflight: dict[int, InFlight] = {}
        self._next_token = 0

    def inflight(self) -> list[InFlight]:
        return list(self._inflight.values())

    async def publish(
        self,
        topic: str,
        key: str | None,
        payload: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        await self._inner.publish(topic, key, payload, headers)

    async def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]:
        source = self._inner.subscribe(topics, group)
        try:
            async for delivery in source:
                event = self._parse(delivery)
                if event is None:
                    yield delivery
                    continue
                await self._limiter.acquire(event.stage)
                token = self._register(event)
                yield _TrackedDelivery(
                    topic=delivery.topic,
                    partition=delivery.partition,
                    offset=delivery.offset,
                    key=delivery.key,
                    value=delivery.value,
                    headers=delivery.headers,
                    inner=delivery,
                    on_done=self._finisher(token, event.stage),
                )
        finally:
            # Registry entries of uncommitted deliveries stay, so the host can release their
            # claims at shutdown.
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                await aclose()

    async def consumer_lag(self, topic: str) -> int:
        return await self._inner.consumer_lag(topic)

    async def dlq_depth(self, stage: Stage) -> int:
        return await self._inner.dlq_depth(stage)

    async def close(self) -> None:
        await self._inner.close()

    @staticmethod
    def _parse(delivery: Delivery) -> StageEvent | None:
        """The stage event of a main-topic delivery, or None when it is not tracked."""
        if delivery.topic.endswith(_UNTRACKED_SUFFIXES):
            return None
        try:
            return StageEvent.model_validate_json(delivery.value)
        except ValidationError:
            return None  # the runner dead-letters malformed events; they hold no slot

    def _register(self, event: StageEvent) -> int:
        self._next_token += 1
        token = self._next_token
        self._inflight[token] = InFlight(event.work_item_id, event.stage, datetime.now(UTC))
        return token

    def _finisher(self, token: int, stage: Stage) -> Callable[[], None]:
        def done() -> None:
            if self._inflight.pop(token, None) is None:
                return  # already committed or released: idempotent
            self._limiter.release(stage)
            if self._on_processed is not None:
                self._on_processed(stage)

        return done
