"""Queries behind the database event bus."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, or_, select, update

from cashapp.data.models.bus_message import BusMessage
from cashapp.data.repository import BaseRepository


class BusMessageRepository(BaseRepository[BusMessage]):
    model = BusMessage

    async def claim(
        self, topics: Sequence[str], *, now: datetime, lease_until: datetime, limit: int
    ) -> list[BusMessage]:
        """Lock up to ``limit`` due, unconsumed messages (highest priority first) and lease them."""
        stmt = (
            select(BusMessage)
            .where(
                BusMessage.topic.in_(list(topics)),
                BusMessage.consumed_at.is_(None),
                or_(BusMessage.leased_until.is_(None), BusMessage.leased_until < now),
            )
            .order_by(BusMessage.priority.desc(), BusMessage.id)
        )
        rows = [*await self.select_for_update_skip_locked(stmt, limit)]
        for row in rows:
            row.leased_until = lease_until
            row.attempts += 1
        await self.session.flush()
        return rows

    async def mark_consumed(self, message_id: int, *, at: datetime) -> None:
        await self.session.execute(
            update(BusMessage).where(BusMessage.id == message_id).values(consumed_at=at)
        )

    async def release(self, message_ids: Sequence[int]) -> None:
        """Hand leased-but-unstarted messages back so another consumer can take them."""
        if not message_ids:
            return
        await self.session.execute(
            update(BusMessage)
            .where(BusMessage.id.in_(list(message_ids)), BusMessage.consumed_at.is_(None))
            .values(leased_until=None)
        )

    async def pending_count(self, topic: str) -> int:
        stmt = (
            select(func.count())
            .select_from(BusMessage)
            .where(BusMessage.topic == topic, BusMessage.consumed_at.is_(None))
        )
        return (await self.session.execute(stmt)).scalar_one()
