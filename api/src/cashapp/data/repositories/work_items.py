"""Queries specific to work items."""

from datetime import datetime

from sqlalchemy import or_, select

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.stages import ItemState, Stage


class WorkItemRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def by_content_hash(self, content_hash: str) -> WorkItem | None:
        stmt = select(WorkItem).where(WorkItem.content_hash == content_hash)
        return (await self.session.execute(stmt)).scalars().first()

    async def claim(self, item_id: int, *, stage: Stage, now: datetime) -> WorkItem | None:
        """Lock a PENDING item at ``stage`` that no person holds; None if it is not claimable.

        The caller (the stage runner) sets state and claim_expires_at itself.
        """
        stmt = select(WorkItem).where(
            WorkItem.id == item_id,
            WorkItem.stage == stage,
            WorkItem.state == ItemState.PENDING,
            or_(WorkItem.lock_owner.is_(None), WorkItem.lock_expires_at <= now),
        )
        rows = await self.select_for_update_skip_locked(stmt)
        return rows[0] if rows else None

    async def get_for_update(self, item_id: int, *, skip_locked: bool = True) -> WorkItem | None:
        stmt = select(WorkItem).where(WorkItem.id == item_id)
        if skip_locked:
            rows = await self.select_for_update_skip_locked(stmt)
            return rows[0] if rows else None
        return (await self.session.execute(stmt.with_for_update())).scalars().first()

    async def children_of(self, parent_id: int) -> list[WorkItem]:
        stmt = select(WorkItem).where(WorkItem.parent_id == parent_id).order_by(WorkItem.id)
        return [*(await self.session.execute(stmt)).scalars().all()]
