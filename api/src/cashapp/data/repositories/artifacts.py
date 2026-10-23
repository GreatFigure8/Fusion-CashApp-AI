"""Queries specific to artifact parts."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.repository import BaseRepository


class ArtifactPartRepository(BaseRepository[ArtifactPart]):
    model = ArtifactPart

    async def for_item(self, work_item_id: int) -> list[ArtifactPart]:
        stmt = (
            select(ArtifactPart)
            .where(ArtifactPart.work_item_id == work_item_id)
            .order_by(ArtifactPart.part_no)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def for_items(self, work_item_ids: Sequence[int]) -> dict[int, list[ArtifactPart]]:
        grouped: dict[int, list[ArtifactPart]] = {item_id: [] for item_id in work_item_ids}
        if not work_item_ids:
            return grouped
        stmt = (
            select(ArtifactPart)
            .where(ArtifactPart.work_item_id.in_(list(work_item_ids)))
            .order_by(ArtifactPart.work_item_id, ArtifactPart.part_no)
        )
        for part in (await self.session.execute(stmt)).scalars():
            grouped[part.work_item_id].append(part)
        return grouped

    async def mark_purged(self, parts: Sequence[ArtifactPart], *, at: datetime) -> None:
        for part in parts:
            part.purged_at = at
        await self.session.flush()


def is_unique_violation(exc: BaseException) -> bool:
    """True for a unique-constraint violation: ORA-00001, or SQLite's UNIQUE failure."""
    if not isinstance(exc, IntegrityError):
        return False
    text = str(exc.orig if exc.orig is not None else exc).upper()
    return "ORA-00001" in text or "UNIQUE" in text
