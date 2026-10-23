"""Queries over RECEIPT_RESERVATION. Flushes, never commits."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cashapp.data.models.receipt_matching import ReceiptReservation
from cashapp.data.repository import BaseRepository
from cashapp.domain.clock import utcnow
from cashapp.domain.receipt_matching import ReservationStatus

_REASON_MAX = 1000


class ReservationConflict(Exception):  # noqa: N818 - pinned name
    """Another transaction already holds an ACTIVE reservation on the receipt."""

    def __init__(self, receipt_id: int) -> None:
        self.receipt_id = receipt_id
        super().__init__(f"receipt {receipt_id} already has an active reservation")


class ReservationRepository(BaseRepository[ReceiptReservation]):
    model = ReceiptReservation

    async def reserve(
        self,
        receipt_id: int,
        item_id: int,
        *,
        receipt_number: str | None = None,
        now: datetime | None = None,
    ) -> ReceiptReservation:
        """Insert an ACTIVE row inside a savepoint, so a lost race leaves the transaction usable."""
        row = ReceiptReservation(
            receipt_id=receipt_id,
            receipt_number=receipt_number,
            work_item_id=item_id,
            status=ReservationStatus.ACTIVE,
            reserved_at=now if now is not None else utcnow(),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            raise ReservationConflict(receipt_id) from exc
        return row

    async def active_for_item(self, item_id: int) -> ReceiptReservation | None:
        stmt = (
            select(ReceiptReservation)
            .where(
                ReceiptReservation.work_item_id == item_id,
                ReceiptReservation.status == ReservationStatus.ACTIVE,
            )
            .order_by(ReceiptReservation.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def active_for_receipt(self, receipt_id: int) -> ReceiptReservation | None:
        """The ACTIVE holder of a receipt, locked; None when free or locked by another session."""
        stmt = select(ReceiptReservation).where(
            ReceiptReservation.receipt_id == receipt_id,
            ReceiptReservation.status == ReservationStatus.ACTIVE,
        )
        rows = await self.select_for_update_skip_locked(stmt)
        return rows[0] if rows else None

    async def _close(
        self,
        row: ReceiptReservation,
        status: ReservationStatus,
        reason: str,
        now: datetime | None,
    ) -> ReceiptReservation:
        return await self.update(
            row,
            status=status,
            released_at=now if now is not None else utcnow(),
            reason=reason[:_REASON_MAX],
        )

    async def consume(
        self, item_id: int, *, now: datetime | None = None
    ) -> ReceiptReservation | None:
        """ACTIVE to CONSUMED once the apply has used the receipt; a no-op with nothing active."""
        row = await self.active_for_item(item_id)
        if row is None:
            return None
        return await self._close(row, ReservationStatus.CONSUMED, "consumed", now)

    async def release(
        self, item_id: int, reason: str, *, now: datetime | None = None
    ) -> ReceiptReservation | None:
        """ACTIVE to RELEASED; a no-op with nothing active."""
        row = await self.active_for_item(item_id)
        if row is None:
            return None
        return await self._close(row, ReservationStatus.RELEASED, reason, now)

    async def release_row(
        self, row: ReceiptReservation, reason: str, *, now: datetime | None = None
    ) -> ReceiptReservation:
        return await self._close(row, ReservationStatus.RELEASED, reason, now)
