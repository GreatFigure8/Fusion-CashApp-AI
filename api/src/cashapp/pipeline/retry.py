"""The retry forwarder: holds a retry event until its ``not_before``, then re-publishes it.

One forwarder serves every stage. It reads nothing outside the bus and writes no database state:
the runner's claim is idempotent, so at-least-once delivery is safe.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from typing import Final

from cashapp.domain.clock import Clock
from cashapp.domain.stages import Stage
from cashapp.pipeline.bus import Delivery, EventBus, close_stream, next_or_stop
from cashapp.pipeline.errors import MalformedEvent
from cashapp.pipeline.events import TopicNamer, parse_event
from cashapp.pipeline.health import CONSUMED_STAGES
from cashapp.pipeline.roles import Container, RoleSpec, RoleState

logger = logging.getLogger(__name__)

RETRY_NAME: Final = "retry-forwarder"
_MAX_BACKOFF_SECONDS = 30


class RetryForwarder:
    def __init__(
        self,
        bus: EventBus,
        group: str,
        *,
        namer: TopicNamer,
        clock: Clock,
        stages: Sequence[Stage] = CONSUMED_STAGES,
        max_sleep_seconds: float = 60.0,
    ) -> None:
        self._bus = bus
        self._group = group
        self._namer = namer
        self._clock = clock
        self._max_sleep = max_sleep_seconds
        self._stage_by_topic = {namer.for_stage(stage, "retry"): stage for stage in stages}
        self._state = RoleState(RETRY_NAME, "starting")

    def state(self) -> RoleState:
        return self._state

    async def _forward(self, delivery: Delivery, stop: asyncio.Event) -> None:
        stage = self._stage_by_topic.get(delivery.topic)
        try:
            event = parse_event(delivery.value)
        except MalformedEvent:
            dlq_stage = stage if stage is not None else CONSUMED_STAGES[0]
            await self._bus.publish(
                self._namer.for_stage(dlq_stage, "dlq"),
                delivery.key,
                delivery.value,
                {
                    **delivery.headers,
                    "error": "malformed",
                    "source-topic": delivery.topic,
                    "source-partition": str(delivery.partition),
                    "source-offset": str(delivery.offset),
                },
            )
            await delivery.commit()
            return
        if event.not_before is not None:
            while True:
                remaining = (event.not_before - self._clock.now()).total_seconds()
                if remaining <= 0:
                    break
                self._state.detail = "waiting"
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=min(remaining, self._max_sleep))
                if stop.is_set():
                    return  # not committed: redelivered after the restart
        self._state.detail = None
        await self._bus.publish(
            self._namer.for_stage(event.stage), delivery.key, delivery.value, delivery.headers
        )
        await delivery.commit()
        self._state.last_activity_at = self._clock.now()

    async def run(self, stop: asyncio.Event) -> None:
        topics = list(self._stage_by_topic)
        self._state.status = "running"
        backoff = 1
        try:
            while not stop.is_set():
                stream = self._bus.subscribe(topics, self._group)
                try:
                    while True:
                        delivery = await next_or_stop(stream, stop)
                        if delivery is None:
                            break
                        await self._forward(delivery, stop)
                        self._state.status = "running"
                        backoff = 1
                except Exception as exc:
                    self._state.status = "degraded"
                    self._state.detail = type(exc).__name__
                    logger.warning(
                        "retry forwarder failed", extra={"error_type": type(exc).__name__}
                    )
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(stop.wait(), timeout=backoff)
                    backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
                finally:
                    await close_stream(stream)
                if stop.is_set():
                    break
        finally:
            self._state.status = "stopped"


def _build_forwarder(container: Container) -> RetryForwarder:
    return RetryForwarder(
        container.bus,
        container.settings.streaming.consumer_group,
        namer=TopicNamer.from_settings(container.settings.streaming),
        clock=container.clock,
    )


RETRY_ROLE: Final = RoleSpec(RETRY_NAME, "consumer", _build_forwarder)
