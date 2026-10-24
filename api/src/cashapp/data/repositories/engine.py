"""Queries behind the engine control API: its audit log, dead letters and in-flight counts.

Flushes, never commits. A dead letter is an outbox row on a ``*.dlq`` topic; it is "replayed"
once ``ENGINE_DLQ_REPLAY`` holds its outbox id, which is a plain-column test (no JSON path).
"""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select

from cashapp.data.models.engine import EngineAudit, EngineDlqReplay
from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository, Page
from cashapp.domain.stages import ItemState, Stage


class EngineAuditRepository(BaseRepository[EngineAudit]):
    model = EngineAudit

    async def page(self, offset: int, limit: int) -> Page[EngineAudit]:
        """Newest first."""
        return await self.list(
            order_by=[EngineAudit.at.desc(), EngineAudit.id.desc()], offset=offset, limit=limit
        )


class EngineDlqReplayRepository(BaseRepository[EngineDlqReplay]):
    model = EngineDlqReplay

    async def replayed_event_ids(self, event_ids: Collection[str]) -> set[str]:
        if not event_ids:
            return set()
        stmt = select(EngineDlqReplay.event_id).where(EngineDlqReplay.event_id.in_(list(event_ids)))
        return {str(value) for value in (await self.session.execute(stmt)).scalars()}


class DeadLetterRepository(BaseRepository[OutboxMessage]):
    model = OutboxMessage

    @staticmethod
    def _unreplayed(topics: Collection[str]) -> list[ColumnElement[bool]]:
        replayed = select(EngineDlqReplay.outbox_id)
        return [OutboxMessage.topic.in_(list(topics)), OutboxMessage.id.not_in(replayed)]

    async def unreplayed(
        self, topics: Collection[str], offset: int, limit: int
    ) -> Page[OutboxMessage]:
        """Dead letters on ``topics`` not yet replayed, newest first."""
        if not topics:
            return Page(items=[], total=0, offset=offset, limit=limit)
        return await self.list(
            where=self._unreplayed(topics),
            order_by=[OutboxMessage.created_at.desc(), OutboxMessage.id.desc()],
            offset=offset,
            limit=limit,
        )

    async def counts_by_topic(self, topics: Collection[str]) -> dict[str, int]:
        if not topics:
            return {}
        stmt = (
            select(OutboxMessage.topic, func.count())
            .where(*self._unreplayed(topics))
            .group_by(OutboxMessage.topic)
        )
        return {topic: int(count) for topic, count in (await self.session.execute(stmt)).all()}

    async def recent_unreplayed(
        self, topics: Collection[str], limit: int
    ) -> Sequence[OutboxMessage]:
        """The newest unreplayed dead letters; replay matches event ids against these."""
        page = await self.unreplayed(topics, 0, limit)
        return page.items


class InFlightRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def in_progress_by_stage(self, now: datetime) -> dict[Stage, int]:
        """Items with a live claim, per stage: work running in any process right now."""
        stmt = (
            select(WorkItem.stage, func.count())
            .where(WorkItem.state == ItemState.IN_PROGRESS, WorkItem.claim_expires_at > now)
            .group_by(WorkItem.stage)
        )
        return {stage: int(count) for stage, count in (await self.session.execute(stmt)).all()}

    async def awaiting_count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(WorkItem)
            .where(WorkItem.state == ItemState.AWAITING_RECEIPT)
        )
        return int((await self.session.execute(stmt)).scalar_one())
