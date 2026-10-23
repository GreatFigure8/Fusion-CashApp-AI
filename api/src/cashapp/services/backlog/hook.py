"""The intake poller's cycle hook that settles backlog batches.

Runs after each intake cycle. It is not a poller: it reads the database and writes nothing else.
"""

import logging
from datetime import datetime
from typing import Final

from cashapp.data.repositories.backlog import BacklogBatchRepository
from cashapp.domain.backlog import ALLOWED_TRANSITIONS, BacklogStatus
from cashapp.domain.principal import SYSTEM_PRINCIPAL
from cashapp.pipeline.roles import Container

logger = logging.getLogger(__name__)

_SWEEP_LIMIT: Final = 500


class BacklogCycleHook:
    """Satisfies the intake ``CycleHook`` protocol."""

    async def on_cycle(self, container: Container, now: datetime) -> None:
        await self._complete_running(container, now)
        await self._sweep_cancelled(container, now)

    async def _complete_running(self, container: Container, now: datetime) -> None:
        """RUNNING and fully imported with nothing PENDING or IN_PROGRESS means DONE.

        Items waiting for a receipt count as settled: they are reported as ``awaiting`` and the
        receipt watcher keeps waking them.
        """
        # Imported here: the service imports the intake path, whose package imports this hook.
        from cashapp.services.backlog.service import append_audit

        async with container.uow_factory() as uow:
            repo = uow.repo(BacklogBatchRepository)
            running = await repo.list_by_status([BacklogStatus.RUNNING], limit=200)
            finished = 0
            for batch in running:
                if batch.imported_at is None or await repo.has_unsettled_items(batch.id):
                    continue
                new_status = ALLOWED_TRANSITIONS[(batch.status, "complete")]
                batch.status = new_status
                batch.finished_at = now
                append_audit(batch, at=now, principal=SYSTEM_PRINCIPAL, action="complete")
                finished += 1
            if finished:
                await uow.commit()
                logger.info("backlog batches completed: count=%s", finished)

    async def _sweep_cancelled(self, container: Container, now: datetime) -> None:
        """Archive items of cancelled batches that were in flight when the batch was cancelled."""
        from cashapp.services.backlog.service import archive_batch_items

        async with container.uow_factory() as uow:
            cancelled = await uow.repo(BacklogBatchRepository).list_by_status(
                [BacklogStatus.CANCELLED], limit=50
            )
        for batch in cancelled:
            archived = await archive_batch_items(
                container.uow_factory,
                batch.id,
                principal=SYSTEM_PRINCIPAL,
                clock=container.clock,
                reason="backlog batch cancelled",
                max_items=_SWEEP_LIMIT,
            )
            if archived:
                logger.info("backlog cancel sweep: batch_id=%s archived=%s", batch.id, archived)
