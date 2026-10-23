"""Queries over EXTRACTION_READING. Flushes, never commits."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.repository import BaseRepository
from cashapp.domain.extraction import ReaderSlot

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list


class ExtractionReadingRepository(BaseRepository[ExtractionReading]):
    model = ExtractionReading

    async def for_item(self, item_id: int) -> list[ExtractionReading]:
        """Every reading of the item, ordered by attempt, reader, id."""
        stmt = (
            select(ExtractionReading)
            .where(ExtractionReading.work_item_id == item_id)
            .order_by(ExtractionReading.attempt, ExtractionReading.reader, ExtractionReading.id)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def latest_for(self, item_id: int) -> dict[ReaderSlot, ExtractionReading]:
        """The highest-attempt reading per reader (ties go to the highest id)."""
        latest: dict[ReaderSlot, ExtractionReading] = {}
        for reading in await self.for_item(item_id):
            latest[reading.reader] = reading  # ordered ascending, so the last one wins
        return latest

    async def max_attempt(self, item_id: int, reader: ReaderSlot) -> int:
        stmt = select(func.max(ExtractionReading.attempt)).where(
            ExtractionReading.work_item_id == item_id,
            ExtractionReading.reader == reader,
        )
        found = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(found) if found is not None else 0

    async def purge_outputs(self, item_ids: Sequence[int], *, at: datetime) -> int:
        """Retention purge: drop the stored model output, keep the audit row. Returns rows."""
        purged = 0
        for start in range(0, len(item_ids), _IN_CHUNK):
            chunk = list(item_ids[start : start + _IN_CHUNK])
            stmt = (
                update(ExtractionReading)
                .where(
                    ExtractionReading.work_item_id.in_(chunk),
                    ExtractionReading.purged_at.is_(None),
                )
                .values(output=None, purged_at=at)
            )
            result = cast("CursorResult[Any]", await self.session.execute(stmt))
            purged += int(result.rowcount)
        return purged
