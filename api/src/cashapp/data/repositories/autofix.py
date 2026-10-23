"""Queries over the auto-fix rows of the work-item history. Flushes, never commits."""

from datetime import datetime

from sqlalchemy import func, select

from cashapp.data.models.work_item import WorkItemHistory
from cashapp.data.repository import BaseRepository
from cashapp.domain.work_item import HistoryAction


class AutoFixHistoryRepository(BaseRepository[WorkItemHistory]):
    model = WorkItemHistory

    async def latest_human_action_at(self, item_id: int) -> datetime | None:
        stmt = select(func.max(WorkItemHistory.at)).where(
            WorkItemHistory.work_item_id == item_id,
            WorkItemHistory.action == HistoryAction.HUMAN_ACTION,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def autofix_rows_since(
        self, item_id: int, since: datetime | None
    ) -> list[WorkItemHistory]:
        """AUTOFIX_ATTEMPT rows strictly after ``since`` (all of them when None), oldest first."""
        stmt = select(WorkItemHistory).where(
            WorkItemHistory.work_item_id == item_id,
            WorkItemHistory.action == HistoryAction.AUTOFIX_ATTEMPT,
        )
        if since is not None:
            stmt = stmt.where(WorkItemHistory.at > since)
        stmt = stmt.order_by(WorkItemHistory.at, WorkItemHistory.id)
        return [*(await self.session.execute(stmt)).scalars().all()]
