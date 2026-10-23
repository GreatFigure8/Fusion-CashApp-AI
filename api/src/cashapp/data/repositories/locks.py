"""Item lock persistence. The only code that assigns the ``lock_*`` columns of a work item."""

from datetime import datetime

from sqlalchemy import select

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository


class ItemLockRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def get_for_lock(self, item_id: int) -> WorkItem | None:
        """Load the row with SELECT ... FOR UPDATE (waiting), refreshing any cached copy."""
        stmt = (
            select(WorkItem)
            .where(WorkItem.id == item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def write_lock(
        self,
        item: WorkItem,
        *,
        owner: str,
        owner_name: str,
        acquired_at: datetime,
        expires_at: datetime,
        now: datetime,
    ) -> WorkItem:
        item.lock_owner = owner
        item.lock_owner_name = owner_name
        item.lock_acquired_at = acquired_at
        item.lock_expires_at = expires_at
        item.updated_at = now
        await self.session.flush()
        return item

    async def clear_lock(self, item: WorkItem, *, now: datetime) -> WorkItem:
        item.lock_owner = None
        item.lock_owner_name = None
        item.lock_acquired_at = None
        item.lock_expires_at = None
        item.updated_at = now
        await self.session.flush()
        return item

    async def live_locks_by_owner(self, owner: str, *, now: datetime) -> list[WorkItem]:
        stmt = (
            select(WorkItem)
            .where(WorkItem.lock_owner == owner, WorkItem.lock_expires_at > now)
            .order_by(WorkItem.lock_expires_at, WorkItem.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]
