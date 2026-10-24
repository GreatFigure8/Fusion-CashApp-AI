"""Read-only aggregate queries behind the progress dashboard. Never writes, never commits.

Every statement is a bounded range on an indexed timestamp or a primary-key range. Bucketing and
rate arithmetic are done by the caller over the fetched rows, so the same code runs on ATP and on
SQLite in tests. Takes the unit of work's session, like ``ReportQueryRepository``.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, NamedTuple, cast

from sqlalchemy import and_, case, distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.applications import ApplicationLedger, LineResult
from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.models.llm_usage import LlmUsage
from cashapp.data.models.receipt_matching import ReceiptReservation
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.domain.adjudication import AdjudicationOrigin
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ReaderSlot, ReadingStatus
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.llm_usage import LlmRole
from cashapp.domain.receipt_matching import ReservationStatus
from cashapp.domain.stages import ItemState
from cashapp.domain.status import APPLIED_LINE_STATUSES, SUCCESS_STATUSES
from cashapp.domain.work_item import ActorKind, HistoryAction

_CHUNK: Final = 500  # Oracle allows at most 1000 items in an IN list


class CurrencyAggRow(NamedTuple):
    currency: str
    amount: Decimal
    receipts: int
    residual: Decimal


class ThroughputRows(NamedTuple):
    applied: list[datetime]
    escalated: list[datetime]


class AutofixAggRow(NamedTuple):
    error_code: ErrorCode
    attempted: int
    fixed: int


class UsageAggRow(NamedTuple):
    role: LlmRole
    model_id: str
    provider: str
    calls: int
    cost_usd: Decimal
    null_cost_calls: int


class AdjudicationPairRow(NamedTuple):
    """A human-corrected extraction with the item's latest reading per slot."""

    work_item_id: int
    final: dict[str, Any]
    reading_a: dict[str, Any] | None
    reading_b: dict[str, Any] | None


class HistoryActivityRow(NamedTuple):
    id: int
    at: datetime
    work_item_id: int
    action: HistoryAction
    from_state: ItemState | None
    to_state: ItemState | None
    error_code: ErrorCode | None
    payload: dict[str, Any] | None
    currency: str | None
    receipt_number: str | None


def _chunks[T](values: Sequence[T]) -> list[Sequence[T]]:
    return [values[i : i + _CHUNK] for i in range(0, len(values), _CHUNK)]


class MetricsQueryRepository:
    """Aggregates over the window ``[start, end)`` plus the current-state counts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ----------------------------------------------------------------- progress

    async def receipts_matched(self, start: datetime, end: datetime) -> int:
        """Items with a live reservation and at least one APPLIED ledger row in the window."""
        reserved = exists().where(
            ReceiptReservation.work_item_id == ApplicationLedger.work_item_id,
            ReceiptReservation.status.in_([ReservationStatus.ACTIVE, ReservationStatus.CONSUMED]),
        )
        stmt = select(func.count(distinct(ApplicationLedger.work_item_id))).where(
            ApplicationLedger.status == LedgerStatus.APPLIED,
            ApplicationLedger.applied_at >= start,
            ApplicationLedger.applied_at < end,
            reserved,
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def applied_by_currency(self, start: datetime, end: datetime) -> list[CurrencyAggRow]:
        """Per item currency: signed applied total, distinct receipts and the line residuals."""
        stmt = (
            select(
                WorkItem.currency,
                func.sum(ApplicationLedger.amount),
                func.count(distinct(ApplicationLedger.receipt_id)),
            )
            .join(WorkItem, WorkItem.id == ApplicationLedger.work_item_id)
            .where(
                ApplicationLedger.status == LedgerStatus.APPLIED,
                ApplicationLedger.applied_at >= start,
                ApplicationLedger.applied_at < end,
                WorkItem.currency.is_not(None),
            )
            .group_by(WorkItem.currency)
            .order_by(WorkItem.currency)
        )
        totals = (await self._session.execute(stmt)).all()
        applied_items = (
            select(ApplicationLedger.work_item_id)
            .where(
                ApplicationLedger.status == LedgerStatus.APPLIED,
                ApplicationLedger.applied_at >= start,
                ApplicationLedger.applied_at < end,
            )
            .scalar_subquery()
        )
        residual_stmt = (
            select(WorkItem.currency, func.sum(LineResult.residual))
            .join(WorkItem, WorkItem.id == LineResult.work_item_id)
            .where(
                LineResult.work_item_id.in_(applied_items),
                LineResult.line_status.in_(list(APPLIED_LINE_STATUSES)),
                LineResult.residual.is_not(None),
                WorkItem.currency.is_not(None),
            )
            .group_by(WorkItem.currency)
        )
        residuals = {
            str(code): Decimal(total)
            for code, total in (await self._session.execute(residual_stmt)).all()
            if code is not None and total is not None
        }
        return [
            CurrencyAggRow(
                currency=str(code),
                amount=Decimal(amount),
                receipts=int(receipts),
                residual=residuals.get(str(code), Decimal(0)),
            )
            for code, amount, receipts in totals
            if code is not None
        ]

    async def done_counts(self, start: datetime, end: datetime) -> tuple[int, int]:
        """(all, untouched): items that reached DONE in the window, and those no USER touched."""
        done = (
            select(distinct(WorkItemHistory.work_item_id))
            .where(
                WorkItemHistory.at >= start,
                WorkItemHistory.at < end,
                WorkItemHistory.to_state == ItemState.DONE,
            )
            .scalar_subquery()
        )
        touched = exists().where(
            WorkItemHistory.work_item_id == WorkItem.id,
            WorkItemHistory.actor_kind == ActorKind.USER,
        )
        base = select(func.count()).select_from(WorkItem).where(WorkItem.id.in_(done))
        everyone = int((await self._session.execute(base)).scalar_one())
        untouched = int((await self._session.execute(base.where(~touched))).scalar_one())
        return everyone, untouched

    async def awaiting(self) -> tuple[int, datetime | None]:
        """(count, oldest ``awaiting_since``) of items waiting for a receipt now."""
        stmt = select(func.count(), func.min(WorkItem.awaiting_since)).where(
            WorkItem.state == ItemState.AWAITING_RECEIPT
        )
        count, oldest = (await self._session.execute(stmt)).one()
        return int(count), oldest

    async def open_exceptions(self, now: datetime) -> tuple[int, int, int]:
        """(total, locked, dead_lettered) over ESCALATED items now."""
        locked = and_(WorkItem.lock_owner.is_not(None), WorkItem.lock_expires_at > now)
        dead = WorkItem.last_error_code == ErrorCode.SYSTEM_DEAD_LETTER
        stmt = select(
            func.count(),
            func.coalesce(func.sum(case((locked, 1), else_=0)), 0),
            func.coalesce(func.sum(case((dead, 1), else_=0)), 0),
        ).where(WorkItem.state == ItemState.ESCALATED)
        total, n_locked, n_dead = (await self._session.execute(stmt)).one()
        return int(total), int(cast("int", n_locked)), int(cast("int", n_dead))

    # ----------------------------------------------------------------- throughput

    async def throughput(self, start: datetime, end: datetime) -> ThroughputRows:
        """Timestamps of items reaching DONE with a success status, and of escalations."""
        applied_stmt = (
            select(WorkItemHistory.at)
            .join(WorkItem, WorkItem.id == WorkItemHistory.work_item_id)
            .where(
                WorkItemHistory.at >= start,
                WorkItemHistory.at < end,
                WorkItemHistory.to_state == ItemState.DONE,
                WorkItem.payment_status.in_(list(SUCCESS_STATUSES)),
            )
        )
        escalated_stmt = select(WorkItemHistory.at).where(
            WorkItemHistory.at >= start,
            WorkItemHistory.at < end,
            WorkItemHistory.to_state == ItemState.ESCALATED,
        )
        applied = [*(await self._session.execute(applied_stmt)).scalars().all()]
        escalated = [*(await self._session.execute(escalated_stmt)).scalars().all()]
        return ThroughputRows(applied=applied, escalated=escalated)

    # ----------------------------------------------------------------- auto-fix

    async def autofix_by_code(self, start: datetime, end: datetime) -> list[AutofixAggRow]:
        """Per error code: items attempted, and of those the ones that are no longer stuck on it."""
        stmt = (
            select(
                WorkItemHistory.work_item_id,
                WorkItemHistory.error_code,
                WorkItem.state,
                WorkItem.last_error_code,
            )
            .join(WorkItem, WorkItem.id == WorkItemHistory.work_item_id)
            .where(
                WorkItemHistory.action == HistoryAction.AUTOFIX_ATTEMPT,
                WorkItemHistory.at >= start,
                WorkItemHistory.at < end,
                WorkItemHistory.error_code.is_not(None),
            )
            .distinct()
        )
        attempted: dict[ErrorCode, dict[int, bool]] = defaultdict(dict)
        for item_id, code, state, last_code in (await self._session.execute(stmt)).all():
            if code is None:
                continue
            fixed = state is not ItemState.ESCALATED and last_code != code
            attempted[code][int(item_id)] = fixed
        rows = [
            AutofixAggRow(code, len(items), sum(1 for ok in items.values() if ok))
            for code, items in attempted.items()
        ]
        return sorted(rows, key=lambda row: (-row.attempted, row.error_code.value))

    # ----------------------------------------------------------------- models

    async def usage_by_role_model(self, start: datetime, end: datetime) -> list[UsageAggRow]:
        null_cost = func.coalesce(func.sum(case((LlmUsage.cost_usd.is_(None), 1), else_=0)), 0)
        stmt = (
            select(
                LlmUsage.role,
                LlmUsage.model_id,
                LlmUsage.provider,
                func.count(),
                func.coalesce(func.sum(LlmUsage.cost_usd), 0),
                null_cost,
            )
            .where(LlmUsage.created_at >= start, LlmUsage.created_at < end)
            .group_by(LlmUsage.role, LlmUsage.model_id, LlmUsage.provider)
            .order_by(LlmUsage.role, LlmUsage.model_id)
        )
        return [
            UsageAggRow(
                role=role,
                model_id=str(model),
                provider=str(provider),
                calls=int(calls),
                cost_usd=Decimal(cast("Decimal", cost)),
                null_cost_calls=int(cast("int", nulls)),
            )
            for role, model, provider, calls, cost, nulls in (
                await self._session.execute(stmt)
            ).all()
        ]

    async def adjudication_agreement(self, start: datetime, end: datetime) -> tuple[int, int]:
        """(agreed, both_readers): MODEL adjudications with both readings, and those with no
        disagreements."""
        stmt = select(Adjudication.disagreements).where(
            Adjudication.origin == AdjudicationOrigin.MODEL,
            Adjudication.created_at >= start,
            Adjudication.created_at < end,
            Adjudication.missing_reader.is_(None),
        )
        found = [*(await self._session.execute(stmt)).scalars().all()]
        return sum(1 for d in found if not d), len(found)

    async def adjudication_origin_counts(self, start: datetime, end: datetime) -> tuple[int, int]:
        """(human, model) adjudications created in the window."""
        stmt = (
            select(Adjudication.origin, func.count())
            .where(Adjudication.created_at >= start, Adjudication.created_at < end)
            .group_by(Adjudication.origin)
        )
        counts = {origin: int(n) for origin, n in (await self._session.execute(stmt)).all()}
        return counts.get(AdjudicationOrigin.HUMAN, 0), counts.get(AdjudicationOrigin.MODEL, 0)

    async def human_corrected_pairs(
        self, start: datetime, end: datetime
    ) -> list[AdjudicationPairRow]:
        """Per item, the latest HUMAN final created in the window with its latest OK reading per
        slot. Purged rows are skipped."""
        human_stmt = (
            select(Adjudication.work_item_id, Adjudication.final)
            .where(
                Adjudication.origin == AdjudicationOrigin.HUMAN,
                Adjudication.created_at >= start,
                Adjudication.created_at < end,
                Adjudication.final.is_not(None),
                Adjudication.purged_at.is_(None),
            )
            .order_by(Adjudication.id)
        )
        finals: dict[int, dict[str, Any]] = {}
        for item_id, final in (await self._session.execute(human_stmt)).all():
            if final:
                finals[int(item_id)] = dict(final)  # the later row wins
        readings: dict[tuple[int, ReaderSlot], dict[str, Any]] = {}
        for chunk in _chunks(list(finals)):
            reading_stmt = (
                select(
                    ExtractionReading.work_item_id,
                    ExtractionReading.reader,
                    ExtractionReading.output,
                )
                .where(
                    ExtractionReading.work_item_id.in_(chunk),
                    ExtractionReading.status == ReadingStatus.OK,
                    ExtractionReading.purged_at.is_(None),
                    ExtractionReading.output.is_not(None),
                )
                .order_by(ExtractionReading.id)
            )
            for item_id, slot, output in (await self._session.execute(reading_stmt)).all():
                if output:
                    readings[(int(item_id), slot)] = dict(output)
        return [
            AdjudicationPairRow(
                work_item_id=item_id,
                final=final,
                reading_a=readings.get((item_id, ReaderSlot.A)),
                reading_b=readings.get((item_id, ReaderSlot.B)),
            )
            for item_id, final in finals.items()
        ]

    async def reader_ok_counts(self, start: datetime, end: datetime) -> dict[ReaderSlot, int]:
        stmt = (
            select(ExtractionReading.reader, func.count())
            .where(
                ExtractionReading.status == ReadingStatus.OK,
                ExtractionReading.created_at >= start,
                ExtractionReading.created_at < end,
            )
            .group_by(ExtractionReading.reader)
        )
        return {slot: int(n) for slot, n in (await self._session.execute(stmt)).all()}

    # ----------------------------------------------------------------- activity

    async def activity(self, limit: int, after_id: int | None = None) -> list[HistoryActivityRow]:
        """Relevant history rows: newest first, or ascending after ``after_id`` when it is given."""
        relevant = or_(
            and_(
                WorkItemHistory.action == HistoryAction.FUSION_WRITE,
                WorkItemHistory.error_code.is_(None),
            ),
            WorkItemHistory.action == HistoryAction.AUTOFIX_ATTEMPT,
            WorkItemHistory.to_state == ItemState.ESCALATED,
            WorkItemHistory.from_state == ItemState.AWAITING_RECEIPT,
        )
        stmt = (
            select(WorkItemHistory, WorkItem.currency)
            .join(WorkItem, WorkItem.id == WorkItemHistory.work_item_id)
            .where(relevant)
            .limit(limit)
        )
        if after_id is None:
            stmt = stmt.order_by(WorkItemHistory.id.desc())
        else:
            stmt = stmt.where(WorkItemHistory.id > after_id).order_by(WorkItemHistory.id)
        found = (await self._session.execute(stmt)).all()
        ledger_ids = {
            int(row.payload["ledger_id"])
            for row, _ in found
            if row.payload and isinstance(row.payload.get("ledger_id"), int)
        }
        numbers: dict[int, str | None] = {}
        for chunk in _chunks(sorted(ledger_ids)):
            num_stmt = select(ApplicationLedger.id, ApplicationLedger.receipt_number).where(
                ApplicationLedger.id.in_(chunk)
            )
            numbers.update({int(i): n for i, n in (await self._session.execute(num_stmt)).all()})
        out: list[HistoryActivityRow] = []
        for row, currency in found:
            payload = dict(row.payload) if row.payload else None
            ledger_id = payload.get("ledger_id") if payload else None
            number = numbers.get(ledger_id) if isinstance(ledger_id, int) else None
            if number is None and payload and isinstance(payload.get("receipt_number"), str):
                number = payload["receipt_number"]
            out.append(
                HistoryActivityRow(
                    id=row.id,
                    at=row.at,
                    work_item_id=row.work_item_id,
                    action=row.action,
                    from_state=row.from_state,
                    to_state=row.to_state,
                    error_code=row.error_code,
                    payload=payload,
                    currency=currency,
                    receipt_number=number,
                )
            )
        return out

    async def latest_history_id(self) -> int:
        stmt = select(func.max(WorkItemHistory.id))
        return int((await self._session.execute(stmt)).scalar_one_or_none() or 0)
