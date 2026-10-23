"""Queries specific to the transactional outbox."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.repository import BaseRepository

_LAST_ERROR_MAX = 4000


class OutboxRepository(BaseRepository[OutboxMessage]):
    model = OutboxMessage

    async def claim_batch(self, *, now: datetime, limit: int) -> list[OutboxMessage]:
        """Lock up to ``limit`` unpublished, due messages, highest priority first."""
        stmt = (
            select(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None), OutboxMessage.not_before <= now)
            .order_by(OutboxMessage.priority.desc(), OutboxMessage.id)
        )
        return [*await self.select_for_update_skip_locked(stmt, limit)]

    async def mark_published(self, rows: Sequence[OutboxMessage], *, at: datetime) -> None:
        for row in rows:
            row.published_at = at
        await self.session.flush()

    async def mark_failed(self, row: OutboxMessage, *, error: str) -> None:
        row.attempts += 1
        row.last_error = error[:_LAST_ERROR_MAX]
        await self.session.flush()

    async def pending_count(self) -> int:
        stmt = (
            select(func.count())
            .select_from(OutboxMessage)
            .where(OutboxMessage.published_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one()
