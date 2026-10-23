"""Queries specific to the work-item history."""

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
