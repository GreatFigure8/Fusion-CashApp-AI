"""Queries over POLLER_HEARTBEAT. Flushes, never commits."""

from datetime import datetime

from sqlalchemy import select

from cashapp.data.models.poller_heartbeat import PollerHeartbeat
from cashapp.data.repository import BaseRepository


class PollerHeartbeatRepository(BaseRepository[PollerHeartbeat]):
    model = PollerHeartbeat

    async def upsert(self, name: str, *, at: datetime, status: str) -> PollerHeartbeat:
        """Select for update, then update or insert: one row per poller."""
        stmt = select(PollerHeartbeat).where(PollerHeartbeat.name == name).with_for_update()
        row = (await self.session.execute(stmt)).scalars().first()
        if row is None:
            return await self.add(
                PollerHeartbeat(name=name, last_cycle_at=at, last_status=status, updated_at=at)
            )
        return await self.update(row, last_cycle_at=at, last_status=status, updated_at=at)

    async def all(self) -> list[PollerHeartbeat]:
        stmt = select(PollerHeartbeat).order_by(PollerHeartbeat.name)
        return [*(await self.session.execute(stmt)).scalars().all()]
