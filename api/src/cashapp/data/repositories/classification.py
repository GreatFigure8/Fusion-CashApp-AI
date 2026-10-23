"""Queries over CLASSIFICATION. Flushes, never commits."""

from collections.abc import Sequence

from sqlalchemy import select

from cashapp.data.models.classification import Classification
from cashapp.data.repository import BaseRepository

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list


class ClassificationRepository(BaseRepository[Classification]):
    model = Classification

    async def for_item(self, item_id: int) -> list[Classification]:
        """Every decision on the item, newest first (ties by id)."""
        stmt = (
            select(Classification)
            .where(Classification.work_item_id == item_id)
            .order_by(Classification.created_at.desc(), Classification.id.desc())
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def latest_for(self, item_id: int) -> Classification | None:
        stmt = (
            select(Classification)
            .where(Classification.work_item_id == item_id)
            .order_by(Classification.created_at.desc(), Classification.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()

    async def latest_for_items(self, item_ids: Sequence[int]) -> dict[int, Classification]:
        """The newest decision per item; items with none are absent. No query for no ids."""
        latest: dict[int, Classification] = {}
        for start in range(0, len(item_ids), _IN_CHUNK):
            chunk = list(item_ids[start : start + _IN_CHUNK])
            stmt = (
                select(Classification)
                .where(Classification.work_item_id.in_(chunk))
                .order_by(Classification.created_at, Classification.id)
            )
            for row in (await self.session.scalars(stmt)).all():
                latest[row.work_item_id] = row  # ascending order, so the last one wins
        return latest
