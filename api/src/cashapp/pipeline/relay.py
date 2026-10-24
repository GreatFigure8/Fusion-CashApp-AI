"""The outbox relay: publishes committed outbox rows to the bus.

It is not a poller of an external system. It is woken in-process after each commit; the bounded
idle wait is crash recovery (rows committed by another process, or left behind by a crash).
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.pipeline.roles import Container, RoleSpec, RoleState

if TYPE_CHECKING:
    from cashapp.pipeline.bus import EventBus

logger = logging.getLogger(__name__)

RELAY_NAME: Final = "relay"
_MAX_ERROR_LENGTH = 500
_MAX_BACKOFF_SECONDS = 30


@dataclass(frozen=True, slots=True)
class OutboxRow:
    id: int
    topic: str
    key: str | None
    priority: int
    created_at: datetime
    attempts: int
    work_item_id: int | None


class PublishThrottle(Protocol):
    """Lets the backlog reprocessor (s35) rate-limit what reaches the bus."""

    async def admit(self, row: OutboxRow) -> bool: ...


class AllowAllThrottle:
    async def admit(self, row: OutboxRow) -> bool:
        return True


class OutboxSignal:
    """A wake-up flag that works across event loops (the instance is process-wide)."""

    def __init__(self) -> None:
        self._flag = False
        self._waiters: list[asyncio.Future[None]] = []

    def notify(self) -> None:
        """Safe to call from an after-commit hook."""
        self._flag = True
        waiters, self._waiters = self._waiters, []
        for waiter in waiters:
            waiter.get_loop().call_soon_threadsafe(_release, waiter)

    async def wait(self, timeout: float) -> bool:  # noqa: ASYNC109 - pinned signature
        """True when notified (the flag is cleared on return), False on timeout."""
        if self._flag:
            self._flag = False
            return True
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(waiter, timeout)
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
        notified = self._flag
        self._flag = False
        return notified


def _release(waiter: asyncio.Future[None]) -> None:
    if not waiter.done():
        waiter.set_result(None)


_signal = OutboxSignal()


def outbox_signal() -> OutboxSignal:
    """The process-wide instance used by ``emit`` / ``enqueue``."""
    return _signal


@dataclass(frozen=True, slots=True)
class _Cycle:
    claimed: int
    admitted: int
    published: int
    failed: int
    throttled: int


def _headers(payload: Mapping[str, Any]) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    for header, field_name in (
        ("schema-version", "schema_version"),
        ("event-id", "event_id"),
        ("trace-id", "trace_id"),
        ("work-item-id", "work_item_id"),
    ):
        value = payload.get(field_name)
        if value is not None:
            headers[header] = str(value)
    return headers


def _view(row: OutboxMessage) -> OutboxRow:
    work_item_id = row.payload.get("work_item_id")
    return OutboxRow(
        id=row.id,
        topic=row.topic,
        key=row.msg_key,
        priority=row.priority,
        created_at=row.created_at,
        attempts=row.attempts,
        work_item_id=work_item_id if isinstance(work_item_id, int) else None,
    )


class OutboxRelay:
    def __init__(
        self,
        uow_factory: UowFactory,
        bus: "EventBus",
        clock: Clock,
        *,
        throttle: PublishThrottle | None = None,
        signal: OutboxSignal | None = None,
        batch_size: int = 100,
        idle_seconds: float = 10.0,
        throttle_wait_seconds: float = 1.0,
    ) -> None:
        self._uow_factory = uow_factory
        self._bus = bus
        self._clock = clock
        self._throttle: PublishThrottle = throttle if throttle is not None else AllowAllThrottle()
        self._signal = signal if signal is not None else outbox_signal()
        self._batch_size = batch_size
        self._idle_seconds = idle_seconds
        self._throttle_wait_seconds = throttle_wait_seconds
        self._state = RoleState(RELAY_NAME, "starting")

    def state(self) -> RoleState:
        return self._state

    async def run_once(self) -> int:
        """One claim / publish / commit cycle; the number of rows published."""
        return (await self._cycle()).published

    async def _cycle(self) -> _Cycle:
        published: list[OutboxMessage] = []
        failed = 0
        throttled = 0
        async with self._uow_factory() as uow:
            rows = await uow.outbox.claim_batch(now=self._clock.now(), limit=self._batch_size)
            for row in rows:
                if not await self._throttle.admit(_view(row)):
                    throttled += 1
                    continue
                try:
                    await self._bus.publish(
                        row.topic,
                        row.msg_key,
                        json.dumps(row.payload, separators=(",", ":")).encode("utf-8"),
                        {**_headers(row.payload), "priority": str(row.priority)},
                    )
                except Exception as exc:
                    failed += 1
                    logger.warning(
                        "outbox publish failed",
                        extra={
                            "outbox_id": row.id,
                            "topic": row.topic,
                            "error_type": type(exc).__name__,
                        },
                    )
                    error = f"{type(exc).__name__}: {str(exc)[:_MAX_ERROR_LENGTH]}"
                    await uow.outbox.mark_failed(row, error=error)
                else:
                    published.append(row)
            if published:
                await uow.outbox.mark_published(published, at=self._clock.now())
            await uow.commit()
        return _Cycle(
            claimed=len(rows),
            admitted=len(published) + failed,
            published=len(published),
            failed=failed,
            throttled=throttled,
        )

    async def _wait(self, stop: asyncio.Event, seconds: float) -> None:
        """Wait for a wake-up signal, the timeout or ``stop``, whichever comes first."""
        signalled = asyncio.ensure_future(self._signal.wait(seconds))
        stopped = asyncio.ensure_future(stop.wait())
        try:
            await asyncio.wait({signalled, stopped}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for pending in (signalled, stopped):
                if not pending.done():
                    pending.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await pending

    async def run(self, stop: asyncio.Event) -> None:
        self._state.status = "running"
        failure_streak = 0
        try:
            while not stop.is_set():
                try:
                    cycle = await self._cycle()
                except Exception as exc:
                    failure_streak += 1
                    self._state.status = "degraded"
                    self._state.detail = type(exc).__name__
                    logger.warning(
                        "outbox relay cycle failed", extra={"error_type": type(exc).__name__}
                    )
                    await self._wait(stop, min(2**failure_streak, _MAX_BACKOFF_SECONDS))
                    continue
                self._state.status = "running"
                self._state.detail = None
                if cycle.claimed:
                    self._state.last_activity_at = self._clock.now()
                if cycle.published:
                    failure_streak = 0
                if cycle.claimed >= self._batch_size and cycle.published:
                    continue
                if cycle.admitted and not cycle.published:
                    failure_streak += 1
                    await self._wait(stop, min(2**failure_streak, _MAX_BACKOFF_SECONDS))
                elif cycle.claimed and not cycle.admitted:
                    await self._wait(stop, self._throttle_wait_seconds)
                else:
                    await self._wait(stop, self._idle_seconds)
        finally:
            self._state.status = "stopped"


def _build_relay(container: Container) -> OutboxRelay:
    throttle: PublishThrottle | None
    try:
        throttle = container.resolve(PublishThrottle)  # type: ignore[type-abstract]
    except KeyError:
        throttle = None
    return OutboxRelay(container.uow_factory, container.bus, container.clock, throttle=throttle)


RELAY_ROLE: Final = RoleSpec(RELAY_NAME, "relay", _build_relay)
