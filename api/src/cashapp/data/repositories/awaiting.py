"""Queries over items parked in AWAITING_RECEIPT: who a new receipt could match, who aged out."""

import logging
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, or_, select

from cashapp.data.models.customer_resolution import CustomerResolutionRow
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.receipt_arrived import ReceiptArrived
from cashapp.domain.stages import ItemState

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATE_LIMIT = 500


def _no_live_lock(now: datetime) -> ColumnElement[bool]:
    return or_(
        WorkItem.lock_owner.is_(None),
        WorkItem.lock_expires_at.is_(None),
        WorkItem.lock_expires_at <= now,
    )


def _within(payment_date: date, anchor: date, window_days: int) -> bool:
    return abs((payment_date - anchor).days) <= window_days


class AwaitingReceiptRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def related_customers(self, item_ids: Sequence[int]) -> dict[int, frozenset[str]]:
        """The latest customer resolution's related customers per item; missing means empty."""
        if not item_ids:
            return {}
        stmt = (
            select(CustomerResolutionRow)
            .where(CustomerResolutionRow.work_item_id.in_(list(item_ids)))
            .order_by(CustomerResolutionRow.created_at, CustomerResolutionRow.id)
        )
        latest: dict[int, frozenset[str]] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            latest[row.work_item_id] = frozenset(row.related_customer_numbers or [])
        return {item_id: latest.get(item_id, frozenset()) for item_id in item_ids}

    async def candidates_for(
        self,
        receipt: ReceiptArrived,
        window_days: int,
        tolerance: Decimal,
        *,
        now: datetime,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> list[WorkItem]:
        """Items a new receipt could match, locked FOR UPDATE SKIP LOCKED.

        Phase 1 narrows in SQL (state, currency, amount, date envelope, live lock). Phase 2 applies
        the exact date and customer rules in Python. Phase 3 locks the survivors and re-checks the
        state, so a concurrent wake or a human lock wins cleanly.
        """
        if receipt.customer_account_number is None:
            return []
        created_on = receipt.creation_date.date()
        window = timedelta(days=window_days)
        low = min(receipt.receipt_date, created_on) - window
        high = max(receipt.receipt_date, created_on) + window
        coarse = (
            select(WorkItem.id, WorkItem.payment_date, WorkItem.customer_account_number)
            .where(
                WorkItem.state == ItemState.AWAITING_RECEIPT,
                or_(WorkItem.currency.is_(None), WorkItem.currency == receipt.currency),
                or_(
                    WorkItem.payment_amount.is_(None),
                    WorkItem.payment_amount <= receipt.unapplied_amount + tolerance,
                ),
                or_(
                    WorkItem.payment_date.is_(None),
                    and_(WorkItem.payment_date >= low, WorkItem.payment_date <= high),
                ),
                _no_live_lock(now),
            )
            .order_by(WorkItem.awaiting_since, WorkItem.id)
            .limit(limit)
        )
        rows = (await self.session.execute(coarse)).all()
        if len(rows) >= limit:
            logger.warning("awaiting-receipt candidate cap hit: limit=%d", limit)

        date_ok = [
            (item_id, customer)
            for item_id, payment_date, customer in rows
            if payment_date is None
            or _within(payment_date, receipt.receipt_date, window_days)
            or _within(payment_date, created_on, window_days)
        ]
        if not date_ok:
            return []
        related = await self.related_customers([item_id for item_id, _ in date_ok])
        wanted = receipt.customer_account_number
        ids = [
            item_id
            for item_id, customer in date_ok
            if customer == wanted or wanted in related.get(item_id, frozenset())
        ]
        if not ids:
            return []

        locking = (
            select(WorkItem)
            .where(
                WorkItem.id.in_(ids),
                WorkItem.state == ItemState.AWAITING_RECEIPT,
                _no_live_lock(now),
            )
            .order_by(WorkItem.awaiting_since, WorkItem.id)
            .execution_options(populate_existing=True)
        )
        return await self.select_for_update_skip_locked(locking)

    async def aged_out(
        self, *, cutoff: datetime, now: datetime, limit: int = 100
    ) -> list[WorkItem]:
        """Awaiting items older than ``cutoff``, no live lock, oldest first, locked SKIP LOCKED."""
        stmt = (
            select(WorkItem)
            .where(
                WorkItem.state == ItemState.AWAITING_RECEIPT,
                WorkItem.awaiting_since.is_not(None),
                WorkItem.awaiting_since < cutoff,
                _no_live_lock(now),
            )
            .order_by(WorkItem.awaiting_since, WorkItem.id)
            .execution_options(populate_existing=True)
        )
        return await self.select_for_update_skip_locked(stmt, limit=limit)
