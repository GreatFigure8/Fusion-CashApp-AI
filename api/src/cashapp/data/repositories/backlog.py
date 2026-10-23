"""Queries for backlog batches, their item counts and their outbox rows. Flushes, never commits."""

from collections.abc import Collection, Sequence
from datetime import UTC, datetime
from typing import Any, Final, cast

from sqlalchemy import String, func, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.engine import CursorResult

from cashapp.data.models.backlog import BacklogBatch
from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.work_items import WorkItemRepository
from cashapp.data.repository import BaseRepository
from cashapp.domain.backlog import BacklogStatus, BatchCounts
from cashapp.domain.stages import ItemState
from cashapp.domain.status import SUCCESS_STATUSES

PAUSED_NOT_BEFORE: Final = datetime(2999, 1, 1, tzinfo=UTC)

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list


class BacklogBatchRepository(BaseRepository[BacklogBatch]):
    model = BacklogBatch

    async def by_name(self, name: str) -> BacklogBatch | None:
        stmt = select(BacklogBatch).where(BacklogBatch.name == name)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_by_status(
        self, statuses: Collection[BacklogStatus] | None, *, limit: int = 100
    ) -> list[BacklogBatch]:
        """Newest first; ``None`` means every status."""
        stmt = select(BacklogBatch)
        if statuses is not None:
            stmt = stmt.where(BacklogBatch.status.in_(list(statuses)))
        stmt = stmt.order_by(BacklogBatch.created_at.desc(), BacklogBatch.id.desc()).limit(limit)
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def item_counts(self, batch_ids: Sequence[int]) -> dict[int, BatchCounts]:
        """One GROUP BY over the batch's items; a batch with no items maps to all zeros."""
        if not batch_ids:
            return {}
        stmt = (
            select(
                WorkItem.batch_id,
                WorkItem.state,
                WorkItem.payment_status,
                func.count().label("n"),
            )
            .where(WorkItem.batch_id.in_(list(batch_ids)))
            .group_by(WorkItem.batch_id, WorkItem.state, WorkItem.payment_status)
        )
        tallies: dict[int, dict[str, int]] = {
            batch_id: dict.fromkeys(
                ("items", "processed", "applied", "escalated", "failed", "awaiting", "in_flight"),
                0,
            )
            for batch_id in batch_ids
        }
        for batch_id, state, payment_status, number in (await self.session.execute(stmt)).all():
            if batch_id is None:
                continue
            tally = tallies[batch_id]
            tally["items"] += number
            if state in {ItemState.DONE, ItemState.ARCHIVED, ItemState.ESCALATED}:
                tally["processed"] += number
            if state == ItemState.DONE:
                if payment_status in SUCCESS_STATUSES:
                    tally["applied"] += number
                else:
                    tally["failed"] += number
            elif state == ItemState.ESCALATED:
                tally["escalated"] += number
            elif state == ItemState.AWAITING_RECEIPT:
                tally["awaiting"] += number
            elif state in {ItemState.PENDING, ItemState.IN_PROGRESS}:
                tally["in_flight"] += number
        return {batch_id: BatchCounts(**tally) for batch_id, tally in tallies.items()}

    async def count_items(self, batch_id: int) -> int:
        stmt = select(func.count()).select_from(WorkItem).where(WorkItem.batch_id == batch_id)
        return int((await self.session.execute(stmt)).scalar_one())

    async def has_unsettled_items(self, batch_id: int) -> bool:
        """Any item still PENDING or IN_PROGRESS."""
        stmt = (
            select(WorkItem.id)
            .where(
                WorkItem.batch_id == batch_id,
                WorkItem.state.in_([ItemState.PENDING, ItemState.IN_PROGRESS]),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None

    async def items_in_states(
        self, batch_id: int, states: Collection[ItemState], *, limit: int, after_id: int = 0
    ) -> list[WorkItem]:
        """Lock up to ``limit`` of the batch's items in ``states``, skipping rows held elsewhere.

        ``after_id`` is a cursor so a caller that skips some items (locked by a person) still
        makes progress through the rest.
        """
        stmt = (
            select(WorkItem)
            .where(
                WorkItem.batch_id == batch_id,
                WorkItem.state.in_(list(states)),
                WorkItem.id > after_id,
            )
            .order_by(WorkItem.id)
        )
        return [*await WorkItemRepository(self.session).select_for_update_skip_locked(stmt, limit)]

    async def batch_for_item(self, work_item_id: int) -> BacklogBatch | None:
        stmt = (
            select(BacklogBatch)
            .join(WorkItem, WorkItem.batch_id == BacklogBatch.id)
            .where(WorkItem.id == work_item_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    def _batch_keys(self, batch_id: int) -> Any:
        """MSG_KEY is ``str(work_item_id)``: match it against the batch's item ids."""
        return OutboxMessage.msg_key.in_(
            select(sql_cast(WorkItem.id, String(255))).where(WorkItem.batch_id == batch_id)
        )

    async def defer_outbox(self, batch_id: int, *, not_before: datetime) -> int:
        """Pause: move the batch's unpublished outbox rows out of the relay's claim window."""
        stmt = (
            update(OutboxMessage)
            .where(
                OutboxMessage.published_at.is_(None),
                OutboxMessage.not_before < not_before,
                self._batch_keys(batch_id),
            )
            .values(not_before=not_before)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return int(result.rowcount)

    async def release_outbox(self, batch_id: int, *, now: datetime) -> int:
        """Resume or cancel: rows parked at the sentinel become due now."""
        stmt = (
            update(OutboxMessage)
            .where(
                OutboxMessage.published_at.is_(None),
                OutboxMessage.not_before == PAUSED_NOT_BEFORE,
                self._batch_keys(batch_id),
            )
            .values(not_before=now)
        )
        result = cast("CursorResult[Any]", await self.session.execute(stmt))
        return int(result.rowcount)

    async def live_outbox_waiting(self, *, now: datetime, min_priority: int) -> bool:
        """Is any live-priority row unpublished and due?"""
        stmt = (
            select(OutboxMessage.id)
            .where(
                OutboxMessage.published_at.is_(None),
                OutboxMessage.not_before <= now,
                OutboxMessage.priority >= min_priority,
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).first() is not None
