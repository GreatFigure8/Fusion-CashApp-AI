"""Housekeeping telemetry: queue depth and bus health pushed to Metrics.

Reads the local database and bus metadata only; it never touches an external system. A processed
event marks the telemetry dirty and the next push is coalesced to at most one per
``min_push_interval``. A health tick every ``tick_seconds`` pushes too and runs the tick hooks.
"""

import asyncio
import logging
import time
from typing import Final, cast

from cashapp.domain.stages import Stage
from cashapp.observability.metrics import Metrics
from cashapp.observability.queue_stats import collect_queue_stats
from cashapp.pipeline.health import BusHealth
from cashapp.pipeline.roles import Container
from cashapp.workers.container import WorkerContainer
from cashapp.workers.hooks import HEALTH_TICK_HOOKS

log = logging.getLogger(__name__)

HEALTH_TICK_SECONDS: Final = 30.0
HOOK_TIMEOUT_SECONDS: Final = 10.0


class HostTelemetry:
    def __init__(
        self,
        container: WorkerContainer,
        *,
        tick_seconds: float = HEALTH_TICK_SECONDS,
        min_push_interval: float = 1.0,
    ) -> None:
        self._container = container
        self._tick_seconds = tick_seconds
        self._min_push_interval = min_push_interval
        self._dirty = asyncio.Event()

    def notify_processed(self, stage: Stage) -> None:
        """Called after every committed event; only marks the telemetry dirty."""
        self._dirty.set()

    async def push_once(self) -> None:
        container = self._container
        metrics = container.resolve(Metrics)
        async with container.uow_factory() as uow:
            stats = await collect_queue_stats(uow, clock=container.clock)
        for stat in stats:
            metrics.queue_depth(stat.stage, stat.state, stat.count, stat.oldest_age_s)
        snapshot = await container.resolve(BusHealth).snapshot()
        for stage, health in snapshot.items():
            metrics.bus_health(stage, health["lag"], health["dlq_depth"])
        await metrics.flush()

    async def tick_once(self) -> None:
        await self.push_once()
        now = self._container.clock.now()
        for hook in list(HEALTH_TICK_HOOKS):
            try:
                await asyncio.wait_for(
                    hook.on_tick(cast(Container, self._container), now),
                    timeout=HOOK_TIMEOUT_SECONDS,
                )
            except Exception:
                log.exception("health tick hook %s failed", type(hook).__name__)

    async def _safely(self, push_only: bool) -> None:
        try:
            if push_only:
                await self.push_once()
            else:
                await self.tick_once()
        except Exception:
            log.exception("telemetry push failed")

    @staticmethod
    async def _wait(stop: asyncio.Event, other: asyncio.Event | None, seconds: float) -> None:
        """Return when stop (or ``other``) is set or the wait ends."""
        waiters = [asyncio.ensure_future(stop.wait())]
        if other is not None:
            waiters.append(asyncio.ensure_future(other.wait()))
        try:
            await asyncio.wait(
                waiters, timeout=max(seconds, 0.0), return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def run(self, stop: asyncio.Event) -> None:
        last_tick = time.monotonic()
        last_push = last_tick - self._min_push_interval
        while not stop.is_set():
            now = time.monotonic()
            until_tick = self._tick_seconds - (now - last_tick)
            if until_tick <= 0:
                await self._safely(push_only=False)
                last_tick = last_push = time.monotonic()
                self._dirty.clear()
                continue
            if self._dirty.is_set():
                spacing = self._min_push_interval - (now - last_push)
                if spacing > 0:
                    await self._wait(stop, None, min(spacing, until_tick))
                    continue
                self._dirty.clear()
                await self._safely(push_only=True)
                last_push = time.monotonic()
                continue
            await self._wait(stop, self._dirty, until_tick)
