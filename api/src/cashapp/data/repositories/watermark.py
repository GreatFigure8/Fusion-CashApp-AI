"""Persistence of the receipt watcher's high-water mark."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cashapp.data.models.receipt_watermark import ReceiptWatermark
from cashapp.data.repository import BaseRepository


class WatermarkRace(Exception):  # noqa: N818
    """Another replica created the pod's watermark row at the same moment."""

    def __init__(self, pod: str) -> None:
        self.pod = pod
        super().__init__(f"watermark row for pod {pod} was created concurrently")


class WatermarkRepository(BaseRepository[ReceiptWatermark]):
    model = ReceiptWatermark

    def _pk(self) -> Any:  # the primary key is the pod name
        return ReceiptWatermark.pod

    async def by_pod(self, pod: str) -> ReceiptWatermark | None:
        """Read the row without a lock."""
        stmt = select(ReceiptWatermark).where(ReceiptWatermark.pod == pod)
        return (await self.session.execute(stmt)).scalars().first()

    async def lock_or_create(
        self, pod: str, *, initial_mark: datetime, now: datetime
    ) -> ReceiptWatermark:
        """Load the row with SELECT ... FOR UPDATE (waiting); insert it when absent. No commit."""
        stmt = (
            select(ReceiptWatermark)
            .where(ReceiptWatermark.pod == pod)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is not None:
            return row
        row = ReceiptWatermark(
            pod=pod, high_water_mark=initial_mark, seen_at_mark={}, updated_at=now
        )
        self.session.add(row)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            # A racing replica created the row first; the caller ends the cycle.
            await self.session.rollback()
            raise WatermarkRace(pod) from exc
        return row
