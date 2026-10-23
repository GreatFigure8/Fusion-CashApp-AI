"""The intake poller's cycle hook that runs the retention purge at most once an hour."""

import logging
from datetime import datetime, timedelta

from cashapp.integrations.storage.base import ObjectStore
from cashapp.pipeline.roles import Container
from cashapp.services.retention.service import RetentionService

logger = logging.getLogger(__name__)


class RetentionCycleHook:
    """Satisfies the intake ``CycleHook`` protocol. The hourly gate is in memory, per process."""

    def __init__(self, *, min_interval: timedelta = timedelta(hours=1), limit: int = 100) -> None:
        self._min_interval = min_interval
        self._limit = limit
        self._last_run: datetime | None = None

    async def on_cycle(self, container: Container, now: datetime) -> None:
        if self._last_run is not None and now - self._last_run < self._min_interval:
            return
        # Set before running: a failing purge must not retry on every cycle.
        self._last_run = now
        config = (await container.config.snapshot()).retention()
        if (
            config.raw_artifact_days is None
            and config.extraction_days is None
            and config.history_payload_days is None
        ):
            return
        report = await RetentionService(config).purge(
            container.uow_factory, container.resolve(ObjectStore), now, limit=self._limit
        )
        logger.info(
            "retention cycle: artifacts=%d readings=%d adjudications=%d history_payloads=%d",
            report.artifacts,
            report.readings,
            report.adjudications,
            report.history_payloads,
        )
