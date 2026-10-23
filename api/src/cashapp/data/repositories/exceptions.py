"""Queries behind the exception workbench. Read-only; flushes nothing and never commits."""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import ColumnElement, and_, exists, func, or_, select

from cashapp.data.models.applications import LineResult
from cashapp.data.models.receipt_matching import MatchCandidate
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repositories.match_candidates import MatchCandidateRepository
from cashapp.data.repository import BaseRepository
from cashapp.domain.paging import Page
from cashapp.domain.stages import ItemState
from cashapp.domain.status import APPLIED_LINE_STATUSES, SUCCESS_STATUSES, LineStatus
from cashapp.domain.work_item import HistoryAction

if TYPE_CHECKING:
    from cashapp.services.exceptions_query import ExceptionFilters

AWAITING_EXCEPTION_AFTER: Final = timedelta(days=1)
"""An item waiting for its receipt becomes an exception once it has waited this long."""

FAILED_LINE_STATUSES: Final[frozenset[LineStatus]] = (
    frozenset(LineStatus)
    - APPLIED_LINE_STATUSES
    - {
        LineStatus.ALLOCATION_PREVIOUSLY_APPLIED,
        LineStatus.ALLOCATION_DRY_RUN,
        LineStatus.ALLOCATION_REVERSED,
    }
)
"""Derived from the one line-status enum, never listed by hand."""

_MONEY_EQ_SLACK: Final = Decimal("0.005")
_IN_CHUNK: Final = 500  # Oracle allows at most 1000 items in an IN list
_ESCAPE: Final = "\\"


def _like_pattern(text: str) -> str:
    """A contains-pattern with ``%``, ``_`` and the escape character escaped."""
    escaped = (
        text.replace(_ESCAPE, _ESCAPE * 2).replace("%", f"{_ESCAPE}%").replace("_", f"{_ESCAPE}_")
    )
    return f"%{escaped}%"


def _parse_work_item_ref(text: str) -> int | None:
    """``WI-20481`` or ``20481`` gives 20481; anything else gives None."""
    candidate = text[3:] if text.upper().startswith("WI-") else text
    return int(candidate) if candidate.isascii() and candidate.isdigit() else None


def _ordering(sort: str) -> list[Any]:
    """The allowlisted orderings. ``-age`` is oldest first (``created_at`` ascending)."""
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    match key:
        case "age":
            column = WorkItem.created_at
            # "age" grows as created_at shrinks, so -age (oldest first) is created_at ascending.
            first = column.asc() if descending else column.desc()
        case "amount":
            first = WorkItem.payment_amount.desc() if descending else WorkItem.payment_amount.asc()
        case "payment_date":
            first = WorkItem.payment_date.desc() if descending else WorkItem.payment_date.asc()
        case "id":
            first = WorkItem.id.desc() if descending else WorkItem.id.asc()
        case _:
            raise ValueError(f"unsupported sort {sort!r}")
    return [first, WorkItem.id.asc()]


class ExceptionsRepository(BaseRepository[WorkItem]):
    model = WorkItem

    @staticmethod
    def _base_set(filters: "ExceptionFilters", now: datetime) -> ColumnElement[bool]:
        failed_line = exists().where(
            LineResult.work_item_id == WorkItem.id,
            LineResult.line_status.in_(FAILED_LINE_STATUSES),
        )
        live_lock = and_(WorkItem.lock_owner.is_not(None), WorkItem.lock_expires_at > now)
        branches: list[ColumnElement[bool]] = [
            WorkItem.state == ItemState.ESCALATED,
            and_(
                WorkItem.state == ItemState.AWAITING_RECEIPT,
                WorkItem.awaiting_since <= now - AWAITING_EXCEPTION_AFTER,
            ),
            failed_line,
            live_lock,
        ]
        if filters.include_auto_applied:
            branches.append(
                and_(
                    WorkItem.state == ItemState.DONE,
                    WorkItem.payment_status.in_(SUCCESS_STATUSES),
                )
            )
        if filters.include_archived:
            branches.append(WorkItem.state == ItemState.ARCHIVED)
        return or_(*branches)

    @staticmethod
    def _search_clause(text: str) -> ColumnElement[bool]:
        item_id = _parse_work_item_ref(text)
        by_id: ColumnElement[bool] | None = WorkItem.id == item_id if item_id is not None else None
        if text.upper().startswith("WI-"):
            return by_id if by_id is not None else WorkItem.id == -1
        pattern = _like_pattern(text)
        clauses: list[ColumnElement[bool]] = [
            WorkItem.payer_name.ilike(pattern, escape=_ESCAPE),
            WorkItem.customer_account_number.ilike(pattern, escape=_ESCAPE),
            exists().where(
                LineResult.work_item_id == WorkItem.id,
                LineResult.transaction_number.ilike(pattern, escape=_ESCAPE),
            ),
            exists().where(
                MatchCandidate.work_item_id == WorkItem.id,
                MatchCandidate.receipt_number == text,
            ),
        ]
        if by_id is not None:
            clauses.append(by_id)
        return or_(*clauses)

    @classmethod
    def _filters(
        cls, filters: "ExceptionFilters", subject: str, now: datetime
    ) -> list[ColumnElement[bool]]:
        where: list[ColumnElement[bool]] = []
        if filters.q:
            where.append(cls._search_clause(filters.q.strip()))
        if filters.amount_min is not None:
            where.append(WorkItem.payment_amount >= filters.amount_min - _MONEY_EQ_SLACK)
        if filters.amount_max is not None:
            where.append(WorkItem.payment_amount <= filters.amount_max + _MONEY_EQ_SLACK)
        if filters.date_from is not None:
            where.append(WorkItem.payment_date >= filters.date_from)
        if filters.date_to is not None:
            where.append(WorkItem.payment_date <= filters.date_to)
        if filters.error_codes:
            where.append(WorkItem.last_error_code.in_(filters.error_codes))
        if filters.stage is not None:
            where.append(WorkItem.stage == filters.stage)
        if filters.locked_by_me:
            where.append(and_(WorkItem.lock_owner == subject, WorkItem.lock_expires_at > now))
        return where

    async def search(
        self, filters: "ExceptionFilters", *, subject: str, now: datetime
    ) -> Page[WorkItem]:
        """One paged SELECT (plus its count) over the exception base set and the filters."""
        return await self.list(
            where=[self._base_set(filters, now), *self._filters(filters, subject, now)],
            order_by=_ordering(filters.sort),
            offset=(filters.page - 1) * filters.page_size,
            limit=filters.page_size,
        )

    async def autofix_counts(
        self, items: Sequence[WorkItem], *, ignore_decisions: Collection[str] = ()
    ) -> dict[int, int]:
        """Per item: AUTOFIX_ATTEMPT rows for its current error code after its latest human action.

        Two grouped reads for the whole page: the latest HUMAN_ACTION per item, then the attempt
        rows. ``ignore_decisions`` drops rows whose payload decision is listed (the no-op rows).
        """
        counts = {item.id: 0 for item in items}
        wanted = {item.id: item.last_error_code for item in items if item.last_error_code}
        ids = [*wanted]
        for start in range(0, len(ids), _IN_CHUNK):
            chunk = ids[start : start + _IN_CHUNK]
            human_stmt = (
                select(WorkItemHistory.work_item_id, func.max(WorkItemHistory.at))
                .where(
                    WorkItemHistory.work_item_id.in_(chunk),
                    WorkItemHistory.action == HistoryAction.HUMAN_ACTION,
                )
                .group_by(WorkItemHistory.work_item_id)
            )
            since = {row[0]: row[1] for row in (await self.session.execute(human_stmt)).all()}
            rows_stmt = select(
                WorkItemHistory.work_item_id,
                WorkItemHistory.error_code,
                WorkItemHistory.at,
                WorkItemHistory.payload,
            ).where(
                WorkItemHistory.work_item_id.in_(chunk),
                WorkItemHistory.action == HistoryAction.AUTOFIX_ATTEMPT,
            )
            for item_id, code, at, payload in (await self.session.execute(rows_stmt)).all():
                if code != wanted[item_id]:
                    continue
                floor = since.get(item_id)
                if floor is not None and at <= floor:
                    continue
                if (payload or {}).get("decision") in ignore_decisions:
                    continue
                counts[item_id] += 1
        return counts

    async def autofix_attempts(self, item_id: int) -> list[WorkItemHistory]:
        """Every AUTOFIX_ATTEMPT row of the item, oldest first."""
        stmt = (
            select(WorkItemHistory)
            .where(
                WorkItemHistory.work_item_id == item_id,
                WorkItemHistory.action == HistoryAction.AUTOFIX_ATTEMPT,
            )
            .order_by(WorkItemHistory.at, WorkItemHistory.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def latest_match_candidates(
        self, item_id: int, *, limit: int = 10
    ) -> list[MatchCandidate]:
        """The newest matching round: chosen first, then by score (s13's accessor, capped)."""
        rows = await MatchCandidateRepository(self.session).for_item(item_id)
        return rows[:limit]
