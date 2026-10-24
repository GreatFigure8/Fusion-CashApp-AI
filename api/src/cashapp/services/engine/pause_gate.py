"""The pause gate: consulted by a consumer before it takes its next delivery.

Pause is runtime config (``engine.paused_stations``), not a signal to a process, so it works
across every worker and survives a restart. A held consumer simply does not fetch: deliveries
stay uncommitted on the bus, in-flight work finishes, and resuming continues from the first
uncommitted offset. This is a wait, not a poll of anything external.
"""

import asyncio
import contextlib
import logging

from cashapp.domain import config_keys as ck
from cashapp.domain.engine import PAUSE_RECHECK_SECONDS, ConsumerRef, Station, gating_stations
from cashapp.services.config import RuntimeConfig

logger = logging.getLogger(__name__)


class PauseGate:
    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config

    async def paused_stations(self) -> frozenset[Station]:
        return frozenset(await self._config.get(ck.ENGINE_PAUSED_STATIONS))

    async def is_paused(self, consumer: ConsumerRef) -> bool:
        """True when any station that gates ``consumer`` is paused."""
        paused = await self.paused_stations()
        return not paused.isdisjoint(gating_stations(consumer))

    async def wait_while_paused(self, consumer: ConsumerRef, stop: asyncio.Event) -> None:
        """Return when ``consumer`` may take its next delivery, or as soon as ``stop`` is set.

        If the pause list cannot be read, the consumer carries on (the same outage stops
        everything else anyway) and a warning is logged.
        """
        while not stop.is_set():
            try:
                paused = await self.is_paused(consumer)
            except Exception as exc:
                logger.warning("pause list unreadable; not holding: error=%s", type(exc).__name__)
                return
            if not paused:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), PAUSE_RECHECK_SECONDS)
