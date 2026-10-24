"""Queries specific to the work-item history."""

from datetime import datetime

from sqlalchemy import func, select

from cashapp.data.models.work_item import WorkItemHistory
from cashapp.data.repository import BaseRepository, Page


class HistoryRepository(BaseRepository[WorkItemHistory]):
    model = WorkItemHistory

    async def for_item(
        self, item_id: int, *, offset: int = 0, limit: int = 200
    ) -> Page[WorkItemHistory]:
        return await self.list(
            where=[WorkItemHistory.work_item_id == item_id],
            order_by=[WorkItemHistory.at, WorkItemHistory.id],
            offset=offset,
            limit=limit,
        )

    async def count_by_actor_since(self, actor_id: str, reasoning: str, since: datetime) -> int:
        """Rows by ``actor_id`` with exactly this reasoning written at or after ``since``."""
        stmt = (
            select(func.count())
            .select_from(WorkItemHistory)
            .where(
                WorkItemHistory.actor_id == actor_id,
                WorkItemHistory.reasoning == reasoning,
                WorkItemHistory.at >= since,
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())
