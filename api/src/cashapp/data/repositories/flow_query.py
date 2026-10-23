"""Read-only queries behind the flow monitor: counts, throughput scans, stage tables and search.

Every statement here is indexed (IX_WORK_ITEM_STAGE_STATE, IX_WORK_ITEM_UPDATED_AT,
IX_WORK_ITEM_CREATED_AT, IX_WIH_ACTION_AT) or a primary-key lookup. Date arithmetic that differs
between Oracle and SQLite (minute buckets, ages) is done by the caller over fetched timestamps or
with bound cut-off datetimes. Flushes nothing and never commits.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import ColumnElement, and_, case, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, aliased

from cashapp.data.models.applications import ApplicationLedger, LineResult
from cashapp.data.models.receipt_matching import MatchCandidate, ReceiptReservation
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repository import BaseRepository, Page
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.domain.work_item import HistoryAction

AWAITING_TILE: Final = "AWAITING_RECEIPT"
LEAVE_STATES: Final = (ItemState.DONE, ItemState.AWAITING_RECEIPT, ItemState.ESCALATED)
ACTIVE_STATES: Final = (ItemState.PENDING, ItemState.IN_PROGRESS)
_BUCKET_DAYS: Final = (3, 8, 31)  # cut-offs between 0-2d, 3-7d, 8-30d and >30d


def _like_prefix(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


class FlowQueryRepository(BaseRepository[WorkItem]):
    model = WorkItem

    # ----------------------------------------------------------------- tile counts

    async def error_counts_by_stage(self) -> dict[Stage, int]:
        """ESCALATED items, plus queued or running items that already carry an error code."""
        stmt = (
            select(WorkItem.stage, func.count())
            .where(
                or_(
                    WorkItem.state == ItemState.ESCALATED,
                    and_(
                        WorkItem.state.in_(ACTIVE_STATES),
                        WorkItem.last_error_code.is_not(None),
                    ),
                )
            )
            .group_by(WorkItem.stage)
        )
        return {stage: int(count) for stage, count in (await self.session.execute(stmt)).all()}

    async def awaiting_buckets(self, *, now: datetime) -> dict[str, int]:
        """Awaiting-receipt items by whole days waited: 0-2d, 3-7d, 8-30d and >30d."""
        cut3, cut8, cut31 = (now - timedelta(days=d) for d in _BUCKET_DAYS)
        entered = func.coalesce(WorkItem.awaiting_since, WorkItem.updated_at)
        stmt = select(
            func.count(case((entered > cut3, 1))),
            func.count(case((and_(entered <= cut3, entered > cut8), 1))),
            func.count(case((and_(entered <= cut8, entered > cut31), 1))),
            func.count(case((entered <= cut31, 1))),
        ).where(WorkItem.state == ItemState.AWAITING_RECEIPT)
        young, week, month, old = (await self.session.execute(stmt)).one()
        return {"0-2d": int(young), "3-7d": int(week), "8-30d": int(month), ">30d": int(old)}

    # ----------------------------------------------------------------- throughput and dwell

    async def leaves_since(self, since: datetime) -> list[tuple[int, Stage, datetime]]:
        """STAGE_TRANSITION rows that left a stage: ``(item_id, from_stage, at)``."""
        stmt = select(
            WorkItemHistory.work_item_id, WorkItemHistory.from_stage, WorkItemHistory.at
        ).where(
            WorkItemHistory.action == HistoryAction.STAGE_TRANSITION,
            WorkItemHistory.at >= since,
            WorkItemHistory.from_stage.is_not(None),
            or_(
                WorkItemHistory.to_stage != WorkItemHistory.from_stage,
                WorkItemHistory.to_state.in_(LEAVE_STATES),
            ),
        )
        return [
            (item_id, stage, at)
            for item_id, stage, at in (await self.session.execute(stmt)).all()
            if stage is not None
        ]

    async def stage_entries(
        self, item_ids: Sequence[int], *, before: datetime
    ) -> list[tuple[int, Stage, datetime]]:
        """Rows that entered a stage: ``(item_id, to_stage, at)`` for the given items."""
        if not item_ids:
            return []
        stmt = select(
            WorkItemHistory.work_item_id, WorkItemHistory.to_stage, WorkItemHistory.at
        ).where(
            WorkItemHistory.work_item_id.in_(list(item_ids)),
            WorkItemHistory.action == HistoryAction.STAGE_TRANSITION,
            WorkItemHistory.at <= before,
            WorkItemHistory.to_stage.is_not(None),
            or_(
                WorkItemHistory.from_stage.is_(None),
                WorkItemHistory.from_stage != WorkItemHistory.to_stage,
            ),
        )
        return [
            (item_id, stage, at)
            for item_id, stage, at in (await self.session.execute(stmt)).all()
            if stage is not None
        ]

    # ----------------------------------------------------------------- KPIs

    async def created_count_since(self, since: datetime) -> int:
        """Items created since ``since``, not counting envelopes (items that have children)."""
        child = aliased(WorkItem)
        stmt = (
            select(func.count())
            .select_from(WorkItem)
            .where(
                WorkItem.created_at >= since,
                ~exists().where(child.parent_id == WorkItem.id),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def finished_since(
        self, since: datetime
    ) -> list[tuple[int, ItemState, PaymentStatus | None, bool]]:
        """DONE or ESCALATED items (not envelopes) updated since ``since``.

        The flag says whether a person touched the item.
        """
        touched = exists().where(
            WorkItemHistory.work_item_id == WorkItem.id,
            WorkItemHistory.action == HistoryAction.HUMAN_ACTION,
        )
        had_human = case((touched, 1), else_=0)
        child = aliased(WorkItem)
        stmt = select(WorkItem.id, WorkItem.state, WorkItem.payment_status, had_human).where(
            WorkItem.state.in_((ItemState.DONE, ItemState.ESCALATED)),
            WorkItem.updated_at >= since,
            ~exists().where(child.parent_id == WorkItem.id),
        )
        return [
            (item_id, state, payment_status, bool(human))
            for item_id, state, payment_status, human in (await self.session.execute(stmt)).all()
        ]

    async def applied_by_currency_since(self, since: datetime) -> list[tuple[str, Decimal]]:
        """Sum of APPLIED ledger amounts since ``since``, per work item currency."""
        total = func.sum(ApplicationLedger.amount)
        stmt = (
            select(WorkItem.currency, total)
            .join(WorkItem, WorkItem.id == ApplicationLedger.work_item_id)
            .where(
                ApplicationLedger.status == LedgerStatus.APPLIED,
                ApplicationLedger.applied_at >= since,
                WorkItem.currency.is_not(None),
            )
            .group_by(WorkItem.currency)
            .order_by(WorkItem.currency)
        )
        return [
            (str(currency).strip(), Decimal(amount))
            for currency, amount in (await self.session.execute(stmt)).all()
            if currency is not None
        ]

    async def done_count_since(self, since: datetime) -> int:
        stmt = (
            select(func.count())
            .select_from(WorkItem)
            .where(WorkItem.state == ItemState.DONE, WorkItem.updated_at >= since)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def escalated_count(self) -> int:
        stmt = (
            select(func.count()).select_from(WorkItem).where(WorkItem.state == ItemState.ESCALATED)
        )
        return int((await self.session.execute(stmt)).scalar_one())

    # ----------------------------------------------------------------- tables and stream

    async def stage_items(
        self, tile: str, *, state: ItemState | None, offset: int, limit: int
    ) -> Page[WorkItem]:
        """One page of the items behind a tile, most urgent first."""
        where: list[ColumnElement[bool]] = []
        if tile == AWAITING_TILE:
            where.append(WorkItem.state == ItemState.AWAITING_RECEIPT)
        else:
            where.append(WorkItem.stage == Stage(tile))
            if state is None:
                where.append(WorkItem.state != ItemState.AWAITING_RECEIPT)
        if state is not None:
            where.append(WorkItem.state == state)
        order = (
            [WorkItem.updated_at.desc(), WorkItem.id]
            if tile == Stage.DONE.value
            else [WorkItem.priority.desc(), WorkItem.created_at, WorkItem.id]
        )
        return await self.list(where=where, order_by=order, offset=offset, limit=limit)

    async def changed_since(self, since: datetime, *, limit: int) -> list[WorkItem]:
        """Items whose UPDATED_AT is at or after ``since``, oldest change first."""
        stmt = (
            select(WorkItem)
            .where(WorkItem.updated_at >= since)
            .order_by(WorkItem.updated_at, WorkItem.id)
            .limit(limit)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def items_by_ids(self, item_ids: Sequence[int]) -> dict[int, WorkItem]:
        if not item_ids:
            return {}
        stmt = select(WorkItem).where(WorkItem.id.in_(list(item_ids)))
        return {item.id: item for item in (await self.session.execute(stmt)).scalars()}

    # ----------------------------------------------------------------- search

    async def search_refs(self, q: str, *, limit: int) -> list[tuple[int, str, str]]:
        """Receipt and invoice references matching ``q``: exact first, then prefix.

        Returns ``(item_id, kind, match)`` with kind ``receipt`` or ``invoice``.
        """
        needle = q.strip().upper()
        if not needle:
            return []
        sources: list[
            tuple[
                str,
                InstrumentedAttribute[int],
                InstrumentedAttribute[str | None],
                list[ColumnElement[bool]],
            ]
        ] = [
            (
                "receipt",
                ReceiptReservation.work_item_id,
                ReceiptReservation.receipt_number,
                [],
            ),
            (
                "receipt",
                MatchCandidate.work_item_id,
                MatchCandidate.receipt_number,
                [MatchCandidate.chosen.is_(True)],
            ),
            ("invoice", LineResult.work_item_id, LineResult.transaction_number, []),
        ]
        found: list[tuple[int, str, str]] = []
        seen: set[tuple[int, str]] = set()
        for exact in (True, False):
            for kind, item_col, ref_col, extra in sources:
                upper = func.upper(ref_col)
                match = upper == needle if exact else upper.like(_like_prefix(needle), escape="\\")
                stmt = (
                    select(item_col, ref_col)
                    .where(match, ref_col.is_not(None), *extra)
                    .order_by(item_col.desc())
                    .limit(limit)
                )
                for item_id, ref in (await self.session.execute(stmt)).all():
                    key = (int(item_id), kind)
                    if ref is None or key in seen:
                        continue
                    seen.add(key)
                    found.append((int(item_id), kind, str(ref)))
                    if len(found) >= limit:
                        return found
        return found
