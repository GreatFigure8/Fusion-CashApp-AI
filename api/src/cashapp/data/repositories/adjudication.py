"""Queries over ADJUDICATION. Flushes, never commits."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.repository import BaseRepository

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list


class AdjudicationRepository(BaseRepository[Adjudication]):
    model = Adjudication

    async def latest_for(self, item_id: int) -> Adjudication | None:
        """The current extraction: newest by (created_at, id), whatever its origin."""
        stmt = (
            select(Adjudication)
            .where(Adjudication.work_item_id == item_id)
            .order_by(Adjudication.created_at.desc(), Adjudication.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()

    async def for_item(self, item_id: int) -> list[Adjudication]:
        """Every adjudication of the item, oldest first."""
        stmt = (
            select(Adjudication)
            .where(Adjudication.work_item_id == item_id)
            .order_by(Adjudication.created_at, Adjudication.id)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def purge_payloads(self, item_ids: Sequence[int], *, at: datetime) -> int:
        """Retention purge: drop the stored values, keep provenance and confidence."""
        purged = 0
        for start in range(0, len(item_ids), _IN_CHUNK):
            chunk = list(item_ids[start : start + _IN_CHUNK])
            stmt = (
                update(Adjudication)
                .where(
                    Adjudication.work_item_id.in_(chunk),
                    Adjudication.purged_at.is_(None),
                )
                .values(final=None, disagreements=None, purged_at=at)
            )
            result = cast("CursorResult[Any]", await self.session.execute(stmt))
            purged += int(result.rowcount)
        return purged
