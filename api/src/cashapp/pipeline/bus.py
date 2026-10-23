"""The event bus interface and its in-memory implementation (tests and ``env == "local"``).

The only other implementation is ``KafkaEventBus`` in ``kafka.py``. Stages never know which one
is plugged in.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from cashapp.domain.stages import Stage
from cashapp.pipeline.events import StageEvent, TopicNamer, default_namer, parse_event

if TYPE_CHECKING:
    from cashapp.services.runtime_settings import RuntimeSettings


@dataclass(slots=True)
class Delivery:
    """One message handed to a consumer. ``commit()`` marks it processed (idempotent)."""

    topic: str
    partition: int
    offset: int
    key: str | None
    value: bytes
    headers: Mapping[str, str]
    on_commit: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    committed: bool = field(default=False, repr=False)

    async def commit(self) -> None:
        if self.committed:
            return
        if self.on_commit is not None:
            await self.on_commit()
        self.committed = True


class EventBus(Protocol):
    async def publish(
        self,
        topic: str,
        key: str | None,
        payload: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None: ...

    def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]:
        """An async generator; closing it (``aclose`` or ``break``) leaves the group cleanly."""
        ...

    async def consumer_lag(self, topic: str) -> int:
        """Messages not yet committed by the consumer group; ``-1`` when unknown."""
        ...

    async def dlq_depth(self, stage: Stage) -> int:
        """Messages in the stage's dead-letter topic; ``-1`` when unknown."""
        ...

    async def close(self) -> None: ...


class CommitTracker:
    """Per-partition commit watermark.

    Deliveries can finish out of order when several are in flight; only the highest *contiguous*
    completed offset may be committed, so a crash never skips an unfinished earlier message.
    """

    def __init__(self) -> None:
        self._next: dict[int, int] = {}
        self._done: dict[int, set[int]] = {}

    def start(self, partition: int, offset: int) -> None:
        """Note a delivery. The first one seen on a partition sets the base."""
        self._next.setdefault(partition, offset)

    def complete(self, partition: int, offset: int) -> int | None:
        """Mark ``offset`` done; the new committable offset (``last + 1``) if it advanced."""
        done = self._done.setdefault(partition, set())
        done.add(offset)
        position = self._next.get(partition, offset)
        advanced = False
        while position in done:
            done.discard(position)
            position += 1
            advanced = True
        self._next[partition] = position
        return position if advanced else None


async def next_or_stop(stream: AsyncIterator[Delivery], stop: asyncio.Event) -> Delivery | None:
    """The next delivery, or ``None`` when ``stop`` is set (or the stream ends) first."""
    fetch = asyncio.ensure_future(anext(stream))
    stopper = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({fetch, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if fetch.done():
            try:
                return fetch.result()
            except StopAsyncIteration:
                return None
        return None
    finally:
        for pending in (fetch, stopper):
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                    await pending


async def close_stream(stream: AsyncIterator[Delivery]) -> None:
    """Close a subscription so the consumer leaves its group cleanly."""
    aclose = getattr(stream, "aclose", None)
    if aclose is not None:
        await aclose()


@dataclass(slots=True)
class _Stored:
    key: str | None
    value: bytes
    headers: Mapping[str, str]


class InMemoryEventBus:
    """Per-topic append-only logs with per-group committed offsets."""

    def __init__(self, *, namer: TopicNamer | None = None, default_group: str = "test") -> None:
        self._namer = namer
        self._default_group = default_group
        self._logs: dict[str, list[_Stored]] = {}
        self._committed: dict[tuple[str, str], int] = {}
        self._waiters: list[asyncio.Future[None]] = []

    def _namer_or_default(self) -> TopicNamer:
        if self._namer is not None:
            return self._namer
        return default_namer()

    def _wake(self) -> None:
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            waiter.get_loop().call_soon_threadsafe(_resolve, waiter)

    async def publish(
        self,
        topic: str,
        key: str | None,
        payload: bytes,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._logs.setdefault(topic, []).append(_Stored(key, payload, dict(headers or {})))
        self._wake()

    def _delivery(self, topic: str, offset: int, group: str, tracker: CommitTracker) -> Delivery:
        stored = self._logs[topic][offset]
        tracker.start(0, offset)

        async def commit() -> None:
            watermark = tracker.complete(0, offset)
            if watermark is not None:
                slot = (group, topic)
                self._committed[slot] = max(self._committed.get(slot, 0), watermark)

        return Delivery(topic, 0, offset, stored.key, stored.value, stored.headers, commit)

    async def subscribe(self, topics: Sequence[str], group: str) -> AsyncIterator[Delivery]:
        trackers = {topic: CommitTracker() for topic in topics}
        positions = {topic: self._committed.get((group, topic), 0) for topic in topics}
        while True:
            for topic in topics:
                if positions[topic] < len(self._logs.get(topic, ())):
                    offset = positions[topic]
                    positions[topic] = offset + 1
                    yield self._delivery(topic, offset, group, trackers[topic])
                    break
            else:
                waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
                self._waiters.append(waiter)
                try:
                    await waiter
                finally:
                    if waiter in self._waiters:
                        self._waiters.remove(waiter)

    async def consumer_lag(self, topic: str) -> int:
        committed = self._committed.get((self._default_group, topic), 0)
        return len(self._logs.get(topic, ())) - committed

    async def dlq_depth(self, stage: Stage) -> int:
        return len(self._logs.get(self._namer_or_default().for_stage(stage, "dlq"), ()))

    async def close(self) -> None:
        self._wake()

    # --- test helpers -------------------------------------------------------------------

    def messages(self, topic: str) -> list[Delivery]:
        """Every message ever published to ``topic`` (no commit hook)."""
        return [
            Delivery(topic, 0, offset, stored.key, stored.value, stored.headers)
            for offset, stored in enumerate(self._logs.get(topic, ()))
        ]

    def published_events(self, topic: str) -> list[StageEvent]:
        return [parse_event(message.value) for message in self.messages(topic)]

    def reset_group(self, group: str) -> None:
        """Forget what ``group`` committed, so every message is delivered again."""
        for slot in [slot for slot in self._committed if slot[0] == group]:
            del self._committed[slot]


def _resolve(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


_shared_memory_bus: InMemoryEventBus | None = None


def build_event_bus(runtime: "RuntimeSettings") -> EventBus:
    """``local`` runs on the process-wide in-memory bus; every other environment uses Kafka."""
    global _shared_memory_bus
    streaming = runtime.streaming()
    if runtime.env == "local":
        if _shared_memory_bus is None:
            _shared_memory_bus = InMemoryEventBus(
                namer=TopicNamer.from_config(streaming, runtime.env),
                default_group=streaming.consumer_group,
            )
        return _shared_memory_bus
    from cashapp.pipeline.kafka import KafkaEventBus

    return KafkaEventBus(
        streaming,
        runtime.secret,
        namer=TopicNamer.from_config(streaming, runtime.env),
    )
