"""Queries for the operations reports. Read-only aggregates plus the stored REPORT_RUN rows.

Flushes, never commits. Every report query over WORK_ITEM, WORK_ITEM_HISTORY and LINE_RESULT lives
here and nowhere else.
"""

from collections.abc import Collection
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import and_, distinct, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from cashapp.data.models.applications import LineResult
from cashapp.data.models.report_run import ReportRun
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repository import BaseRepository
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.reports import ReportKind
from cashapp.domain.stages import TERMINAL_STATES, ItemState
from cashapp.domain.status import APPLIED_LINE_STATUSES, SUCCESS_STATUSES, LineStatus
from cashapp.domain.work_item import HistoryAction


class PartiallyPaidRecord(NamedTuple):
    work_item_id: int
    transaction_number: str | None
    balance_before: Decimal | None
    applied_amount: Decimal | None
    discount_amount: Decimal | None
    line_status: LineStatus | None
    reason: str | None
    currency: str | None
    customer_account_number: str | None
    payer_name: str | None


class ReportRunRepository(BaseRepository[ReportRun]):
    model = ReportRun

    async def find(self, kind: ReportKind, report_date: date) -> ReportRun | None:
        stmt = select(ReportRun).where(ReportRun.kind == kind, ReportRun.report_date == report_date)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ReportQueryRepository:
    """Aggregates over the day window ``[start, end)``. Takes the unit of work's session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def items_in(self, start: datetime, end: datetime) -> int:
        """Items created in the window, leaving out envelope parents (rows that have children)."""
        child = aliased(WorkItem)
        has_child = exists().where(child.parent_id == WorkItem.id)
        stmt = select(func.count()).where(
            WorkItem.created_at >= start, WorkItem.created_at < end, ~has_child
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def completions(self, start: datetime, end: datetime) -> tuple[int, int]:
        """(completed, auto_applied): items that reached DONE in the window, and of those the
        ones with a success payment status that no person ever touched."""
        done_in_window = (
            select(WorkItemHistory.work_item_id)
            .distinct()
            .where(
                WorkItemHistory.at >= start,
                WorkItemHistory.at < end,
                WorkItemHistory.to_state == ItemState.DONE,
            )
            .scalar_subquery()
        )
        completed_stmt = (
            select(func.count()).select_from(WorkItem).where(WorkItem.id.in_(done_in_window))
        )
        touched = exists().where(
            WorkItemHistory.work_item_id == WorkItem.id,
            WorkItemHistory.action == HistoryAction.HUMAN_ACTION,
        )
        auto_stmt = completed_stmt.where(
            WorkItem.payment_status.in_(list(SUCCESS_STATUSES)), ~touched
        )
        completed = (await self._session.execute(completed_stmt)).scalar_one()
        auto_applied = (await self._session.execute(auto_stmt)).scalar_one()
        return completed, auto_applied

    async def applied_by_currency(
        self, start: datetime, end: datetime
    ) -> list[tuple[str, Decimal]]:
        """Sum of applied line amounts per item currency, sorted by currency."""
        total = func.sum(LineResult.applied_amount)
        stmt = (
            select(WorkItem.currency, total)
            .join(WorkItem, WorkItem.id == LineResult.work_item_id)
            .where(
                LineResult.line_status.in_(list(APPLIED_LINE_STATUSES)),
                LineResult.updated_at >= start,
                LineResult.updated_at < end,
                WorkItem.currency.is_not(None),
                LineResult.applied_amount.is_not(None),
            )
            .group_by(WorkItem.currency)
            .order_by(WorkItem.currency)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            (str(code), Decimal(amount))
            for code, amount in rows
            if code is not None and amount is not None
        ]

    async def failures_by_code(self, start: datetime, end: datetime) -> list[tuple[ErrorCode, int]]:
        """Distinct (item, error code) pairs in the window, counted per code."""
        items = func.count(distinct(WorkItemHistory.work_item_id))
        stmt = (
            select(WorkItemHistory.error_code, items)
            .where(
                WorkItemHistory.at >= start,
                WorkItemHistory.at < end,
                WorkItemHistory.error_code.is_not(None),
            )
            .group_by(WorkItemHistory.error_code)
        )
        rows = (await self._session.execute(stmt)).all()
        pairs = [(ErrorCode(row[0]), int(row[1])) for row in rows if row[0] is not None]
        return sorted(pairs, key=lambda pair: (-pair[1], pair[0].value))

    async def escalations(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count(distinct(WorkItemHistory.work_item_id))).where(
            WorkItemHistory.at >= start,
            WorkItemHistory.at < end,
            WorkItemHistory.to_state == ItemState.ESCALATED,
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def open_item_ages(self, end: datetime) -> list[datetime]:
        """``coalesce(awaiting_since, created_at)`` of every item still open at ``end``."""
        since = func.coalesce(WorkItem.awaiting_since, WorkItem.created_at)
        stmt = select(since).where(
            WorkItem.state.not_in(list(TERMINAL_STATES)), WorkItem.created_at < end
        )
        return [*(await self._session.execute(stmt)).scalars().all()]

    async def partially_paid(
        self,
        start: datetime,
        end: datetime,
        statuses: Collection[LineStatus],
        limit: int,
    ) -> list[PartiallyPaidRecord]:
        """Line results in ``statuses`` updated in the window, newest first."""
        stmt = (
            select(
                LineResult.work_item_id,
                LineResult.transaction_number,
                LineResult.balance_before,
                LineResult.applied_amount,
                LineResult.discount_amount,
                LineResult.line_status,
                LineResult.reason,
                WorkItem.currency,
                WorkItem.customer_account_number,
                WorkItem.payer_name,
            )
            .join(WorkItem, WorkItem.id == LineResult.work_item_id)
            .where(
                and_(
                    LineResult.line_status.in_(list(statuses)),
                    LineResult.updated_at >= start,
                    LineResult.updated_at < end,
                )
            )
            .order_by(LineResult.updated_at.desc(), LineResult.id.desc())
            .limit(limit)
        )
        return [
            PartiallyPaidRecord(
                work_item_id=row.work_item_id,
                transaction_number=row.transaction_number,
                balance_before=row.balance_before,
                applied_amount=row.applied_amount,
                discount_amount=row.discount_amount,
                line_status=row.line_status,
                reason=row.reason,
                currency=row.currency,
                customer_account_number=row.customer_account_number,
                payer_name=row.payer_name,
            )
            for row in (await self._session.execute(stmt)).all()
        ]
