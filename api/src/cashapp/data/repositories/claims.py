"""Queries over claimed (IN_PROGRESS) work items, used by worker start-up recovery and shutdown."""

from datetime import datetime

from sqlalchemy import select

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.stages import ItemState, Stage


class ClaimRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def expired_claims(self, *, now: datetime, limit: int) -> list[WorkItem]:
        """Lock up to ``limit`` IN_PROGRESS items whose claim has expired, skipping locked rows."""
        stmt = (
            select(WorkItem)
            .where(WorkItem.state == ItemState.IN_PROGRESS, WorkItem.claim_expires_at < now)
            .order_by(WorkItem.id)
        )
        return await self.select_for_update_skip_locked(stmt, limit)

    async def in_progress_for_update(self, item_id: int, *, stage: Stage) -> WorkItem | None:
        """Lock the item (waiting for any writer) if it is still IN_PROGRESS at ``stage``."""
        stmt = select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.stage == stage,
            WorkItem.state == ItemState.IN_PROGRESS,
        )
        return (await self.session.execute(stmt.with_for_update())).scalars().first()
