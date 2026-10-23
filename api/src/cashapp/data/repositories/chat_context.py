"""Read-only aggregates the chat feeds to the model."""

from datetime import datetime

from sqlalchemy import func, select

from cashapp.data.models.work_item import WorkItemHistory
from cashapp.data.repository import BaseRepository
from cashapp.domain.error_codes import ErrorCode


class ChatContextRepository(BaseRepository[WorkItemHistory]):
    model = WorkItemHistory

    async def failures_by_code_since(self, since: datetime) -> list[tuple[ErrorCode, int]]:
        """History rows with an error code at or after ``since``, counting distinct items per code.

        Most frequent first, then by code, so the output order is stable.
        """
        items = func.count(func.distinct(WorkItemHistory.work_item_id))
        stmt = (
            select(WorkItemHistory.error_code, items)
            .where(WorkItemHistory.error_code.is_not(None), WorkItemHistory.at >= since)
            .group_by(WorkItemHistory.error_code)
            .order_by(items.desc(), WorkItemHistory.error_code)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(code, int(count)) for code, count in rows if code is not None]
