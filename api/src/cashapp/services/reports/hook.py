"""The intake poller's cycle hook that generates and emails yesterday's daily summary.

There is no scheduler: the first intake cycle after the configured UTC cutover time each day
does the work. An in-process gate keeps later cycles from touching the database.
"""

import logging
from datetime import UTC, date, datetime

from cashapp.pipeline.roles import Container
from cashapp.services.reports.service import ReportService

logger = logging.getLogger(__name__)


class DailySummaryCycleHook:
    """Satisfies the intake ``CycleHook`` protocol structurally; does not import ``hooks.py``."""

    def __init__(self, service: ReportService | None = None) -> None:
        self._service = service
        self._done_for: date | None = None

    async def on_cycle(self, container: Container, now: datetime) -> None:
        utc_now = now.astimezone(UTC)
        today = utc_now.date()
        if self._done_for == today:
            return
        config = await container.config.snapshot()
        if utc_now.time() < config.reports().daily_summary_cutover:
            return
        service = self._service or ReportService(
            clock=container.clock, runtime_settings=container.runtime
        )
        generated = await service.run_cutover(container.uow_factory, utc_now, config)
        # Any failure above propagated, leaving the gate open so the next cycle retries.
        self._done_for = today
        if generated:
            logger.info("daily summary generated for %s", today.isoformat())
