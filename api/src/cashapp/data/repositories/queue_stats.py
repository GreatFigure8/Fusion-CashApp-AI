"""The grouped queue-depth query behind the worker host's metrics loop and the flow API."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.stages import TERMINAL_STATES, ItemState, Stage


@dataclass(frozen=True, slots=True)
class QueueStatRow:
    stage: Stage
    state: ItemState
    count: int
    oldest_at: datetime | None


class QueueStatsRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def grouped_counts(self, *, include_terminal: bool = False) -> list[QueueStatRow]:
        """One GROUP BY over stage and state; the age is computed by the caller, not in SQL."""
        entered = func.coalesce(WorkItem.awaiting_since, WorkItem.updated_at)
        stmt = select(WorkItem.stage, WorkItem.state, func.count(), func.min(entered))
        if not include_terminal:
            stmt = stmt.where(WorkItem.state.not_in(TERMINAL_STATES))
        stmt = stmt.group_by(WorkItem.stage, WorkItem.state)
        rows = (await self.session.execute(stmt)).all()
        return [
            QueueStatRow(stage=stage, state=state, count=count, oldest_at=oldest)
            for stage, state, count, oldest in rows
        ]
