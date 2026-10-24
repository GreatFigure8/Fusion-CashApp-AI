"""Queries behind the Review board: uploaded (MANUAL) items with their filename and confidence."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, func, select

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repository import BaseRepository, Page
from cashapp.domain.review import RECEIVED_FOR_REVIEW
from cashapp.domain.stages import TERMINAL_STATES, ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.domain.work_item import SourceKind


@dataclass(frozen=True, slots=True)
class ReviewQueueRecord:
    item_id: int
    filename: str | None
    stage: Stage
    state: ItemState
    payment_status: PaymentStatus | None
    created_at: datetime
    confidence: float | None


def _visible(open_only: bool) -> list[ColumnElement[bool]]:
    where: list[ColumnElement[bool]] = [
        WorkItem.source_kind == SourceKind.MANUAL,
        WorkItem.state != ItemState.ARCHIVED,
    ]
    if open_only:
        where.append(WorkItem.state.not_in(TERMINAL_STATES))
    return where


class ReviewQueueRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def page(self, offset: int, limit: int, open_only: bool) -> Page[ReviewQueueRecord]:
        base = await self.list(
            where=_visible(open_only),
            order_by=[WorkItem.created_at.desc(), WorkItem.id.desc()],
            offset=offset,
            limit=limit,
        )
        ids = [item.id for item in base.items]
        filenames = await self._filenames(ids)
        confidences = await self._confidences(ids)
        records = [
            ReviewQueueRecord(
                item_id=item.id,
                filename=filenames.get(item.id),
                stage=item.stage,
                state=item.state,
                payment_status=item.payment_status,
                created_at=item.created_at,
                confidence=confidences.get(item.id),
            )
            for item in base.items
        ]
        return Page(items=records, total=base.total, offset=offset, limit=limit)

    async def open_count(self) -> int:
        stmt = select(func.count()).select_from(WorkItem).where(*_visible(True))
        return int((await self.session.execute(stmt)).scalar_one())

    async def _filenames(self, ids: Sequence[int]) -> dict[int, str]:
        if not ids:
            return {}
        stmt = (
            select(WorkItemHistory)
            .where(
                WorkItemHistory.work_item_id.in_(list(ids)),
                WorkItemHistory.reasoning == RECEIVED_FOR_REVIEW,
            )
            .order_by(WorkItemHistory.at, WorkItemHistory.id)
        )
        names: dict[int, str] = {}
        for row in (await self.session.scalars(stmt)).all():
            payload: dict[str, Any] = row.payload or {}
            upload = cast("dict[str, Any]", payload.get("upload") or {})
            name: Any = upload.get("filename")
            if isinstance(name, str) and row.work_item_id not in names:
                names[row.work_item_id] = name
        return names

    async def _confidences(self, ids: Sequence[int]) -> dict[int, float]:
        if not ids:
            return {}
        stmt = (
            select(Adjudication.work_item_id, Adjudication.confidence)
            .where(Adjudication.work_item_id.in_(list(ids)))
            .order_by(Adjudication.created_at, Adjudication.id)
        )
        latest: dict[int, float] = {}
        for item_id, confidence in (await self.session.execute(stmt)).all():
            latest[item_id] = float(confidence)  # oldest first, so the newest wins
        return latest
