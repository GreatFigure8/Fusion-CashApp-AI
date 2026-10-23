"""Queries over LINE_RESULT and APPLICATION_LEDGER. Flushes, never commits."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from cashapp.data.models.applications import ApplicationLedger, LineResult
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.ledger import LedgerStatus, idempotency_key

_RESETTABLE = frozenset({LedgerStatus.PLANNED, LedgerStatus.FAILED, LedgerStatus.DRY_RUN})


def _check_columns(model: type[Any], names: Any) -> None:
    for name in names:
        if not hasattr(model, name):
            raise AttributeError(f"{model.__name__} has no attribute {name!r}")


class LineResultRepository(BaseRepository[LineResult]):
    model = LineResult

    async def upsert(self, item_id: int, line_no: int, **cols: Any) -> LineResult:
        """Create or update the one result row for ``(item_id, line_no)``."""
        _check_columns(LineResult, cols)
        existing = await self.get_line(item_id, line_no)
        if existing is not None:
            return await self.update(existing, **cols)
        return await self.add(LineResult(work_item_id=item_id, line_no=line_no, **cols))

    async def get_line(self, item_id: int, line_no: int) -> LineResult | None:
        stmt = select(LineResult).where(
            LineResult.work_item_id == item_id, LineResult.line_no == line_no
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def for_item(self, item_id: int) -> list[LineResult]:
        stmt = (
            select(LineResult)
            .where(LineResult.work_item_id == item_id)
            .order_by(LineResult.line_no, LineResult.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]


class ApplicationLedgerRepository(BaseRepository[ApplicationLedger]):
    model = ApplicationLedger

    async def planned_for(self, item_id: int) -> list[ApplicationLedger]:
        stmt = (
            select(ApplicationLedger)
            .where(
                ApplicationLedger.work_item_id == item_id,
                ApplicationLedger.status == LedgerStatus.PLANNED,
            )
            .order_by(ApplicationLedger.apply_seq, ApplicationLedger.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def for_item(self, item_id: int) -> list[ApplicationLedger]:
        stmt = (
            select(ApplicationLedger)
            .where(ApplicationLedger.work_item_id == item_id)
            .order_by(ApplicationLedger.apply_seq, ApplicationLedger.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def applied_for(self, item_id: int) -> list[ApplicationLedger]:
        stmt = (
            select(ApplicationLedger)
            .where(
                ApplicationLedger.work_item_id == item_id,
                ApplicationLedger.status == LedgerStatus.APPLIED,
            )
            .order_by(ApplicationLedger.apply_seq, ApplicationLedger.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def mark(
        self, row: ApplicationLedger, status: LedgerStatus, **cols: Any
    ) -> ApplicationLedger:
        return await self.update(row, status=status, **cols)

    async def upsert_planned(
        self,
        item_id: int,
        *,
        line_no: int,
        receipt_id: int,
        receipt_number: str | None,
        customer_trx_id: int,
        amount: Decimal,
        apply_seq: int,
        discount_amount: Decimal | None = None,
    ) -> ApplicationLedger:
        """Plan one application. An APPLIED row is left alone; a REVERSED one gets a new row.

        The idempotency key is ``item:receipt:trx``; a replan after a reversal (s38) gets the
        suffix ``#n`` so the unique key still holds.
        """
        base = idempotency_key(item_id, receipt_id, customer_trx_id)
        stmt = (
            select(ApplicationLedger)
            .where(
                ApplicationLedger.idempotency_key.like(f"{base}#%")
                | (ApplicationLedger.idempotency_key == base)
            )
            .order_by(ApplicationLedger.id)
        )
        rows = [*(await self.session.execute(stmt)).scalars().all()]
        live = [r for r in rows if r.status is not LedgerStatus.REVERSED]
        if live:
            row = live[-1]
            if row.status in _RESETTABLE:
                return await self.update(
                    row,
                    status=LedgerStatus.PLANNED,
                    line_no=line_no,
                    receipt_number=receipt_number,
                    amount=amount,
                    apply_seq=apply_seq,
                    discount_amount=discount_amount,
                    error_code=None,
                )
            return row
        key = base if not rows else f"{base}#{len(rows)}"
        return await self.add(
            ApplicationLedger(
                work_item_id=item_id,
                line_no=line_no,
                receipt_id=receipt_id,
                receipt_number=receipt_number,
                customer_trx_id=customer_trx_id,
                apply_seq=apply_seq,
                amount=amount,
                discount_amount=discount_amount,
                idempotency_key=key,
                status=LedgerStatus.PLANNED,
            )
        )

    async def reload_item(self, item: WorkItem) -> WorkItem:
        """Refresh the item row ``FOR UPDATE`` (the stations' lock and claim re-check)."""
        await self.session.refresh(item, with_for_update=True)
        return item

    async def mark_applied(
        self,
        row: ApplicationLedger,
        *,
        fusion_application_id: int | None,
        amount: Decimal,
        applied_at: datetime,
        applied_by: str,
        **cols: Any,
    ) -> ApplicationLedger:
        return await self.mark(
            row,
            LedgerStatus.APPLIED,
            fusion_application_id=fusion_application_id,
            amount=amount,
            applied_at=applied_at,
            applied_by=applied_by,
            error_code=None,
            **cols,
        )
