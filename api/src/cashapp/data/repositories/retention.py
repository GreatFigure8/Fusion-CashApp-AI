"""Queries for the retention purge. Flushes, never commits."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.models.lab import LabReplay, LabReplayItem
from cashapp.data.models.retention import RetentionPurge
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repository import BaseRepository
from cashapp.domain.lab import ReplayStatus
from cashapp.domain.retention import PurgeKind, PurgeStatus
from cashapp.domain.stages import TERMINAL_STATES

_IN_CHUNK = 500  # Oracle allows at most 1000 items in an IN list
_TEXT_SUFFIX = ".txt"


def _eligible(cutoff: datetime) -> list[ColumnElement[bool]]:
    """Terminal and untouched since before the cutoff: the one eligibility rule."""
    return [WorkItem.state.in_(TERMINAL_STATES), WorkItem.updated_at < cutoff]


def _chunks[T](values: Sequence[T]) -> list[Sequence[T]]:
    return [values[start : start + _IN_CHUNK] for start in range(0, len(values), _IN_CHUNK)]


class RetentionRepository(BaseRepository[RetentionPurge]):
    model = RetentionPurge

    async def artifact_candidates(self, cutoff: datetime, *, limit: int) -> list[int]:
        """Eligible items whose raw artifact has not been purged, oldest id first."""
        purged = exists().where(
            RetentionPurge.work_item_id == WorkItem.id,
            RetentionPurge.kind == PurgeKind.ARTIFACT,
        )
        live_part = exists().where(
            ArtifactPart.work_item_id == WorkItem.id, ArtifactPart.purged_at.is_(None)
        )
        stmt = (
            select(WorkItem.id)
            .where(
                *_eligible(cutoff),
                ~purged,
                or_(live_part, WorkItem.artifact_key.is_not(None)),
            )
            .order_by(WorkItem.id)
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def extraction_candidates(self, cutoff: datetime, *, limit: int) -> list[int]:
        """Eligible items that still hold a reading or adjudication payload."""
        live_reading = exists().where(
            ExtractionReading.work_item_id == WorkItem.id, ExtractionReading.purged_at.is_(None)
        )
        live_adjudication = exists().where(
            Adjudication.work_item_id == WorkItem.id, Adjudication.purged_at.is_(None)
        )
        stmt = (
            select(WorkItem.id)
            .where(*_eligible(cutoff), or_(live_reading, live_adjudication))
            .order_by(WorkItem.id)
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def history_candidates(self, cutoff: datetime, *, limit: int) -> list[int]:
        """History row ids of eligible items that still carry a payload."""
        stmt = (
            select(WorkItemHistory.id)
            .join(WorkItem, WorkItem.id == WorkItemHistory.work_item_id)
            .where(
                *_eligible(cutoff),
                WorkItemHistory.payload.is_not(None),
                WorkItemHistory.purged_at.is_(None),
            )
            .order_by(WorkItemHistory.id)
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def lab_item_candidates(self, cutoff: datetime, *, limit: int) -> list[int]:
        """Finished (DONE or FAILED) replays older than the cutoff that still hold items."""
        has_items = exists().where(LabReplayItem.replay_id == LabReplay.id)
        stmt = (
            select(LabReplay.id)
            .where(
                LabReplay.status.in_([ReplayStatus.DONE, ReplayStatus.FAILED]),
                LabReplay.finished_at.is_not(None),
                LabReplay.finished_at < cutoff,
                has_items,
            )
            .order_by(LabReplay.id)
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def count_lab_items(self, replay_ids: Sequence[int]) -> int:
        """How many replay item rows a purge of ``replay_ids`` would delete (dry run)."""
        total = 0
        for chunk in _chunks(list(replay_ids)):
            stmt = select(func.count()).where(LabReplayItem.replay_id.in_(list(chunk)))
            total += int((await self.session.execute(stmt)).scalar_one())
        return total

    async def purge_lab_items(self, replay_ids: Sequence[int], cutoff: datetime) -> int:
        """Delete the items of finished replays; status and age are re-checked in the DELETE."""
        purged = 0
        for chunk in _chunks(list(replay_ids)):
            still_finished = (
                select(LabReplay.id)
                .where(
                    LabReplay.id.in_(list(chunk)),
                    LabReplay.status.in_([ReplayStatus.DONE, ReplayStatus.FAILED]),
                    LabReplay.finished_at.is_not(None),
                    LabReplay.finished_at < cutoff,
                )
                .scalar_subquery()
            )
            stmt = delete(LabReplayItem).where(LabReplayItem.replay_id.in_(still_finished))
            result = cast("CursorResult[Any]", await self.session.execute(stmt))
            purged += int(result.rowcount)
        return purged

    async def keys_still_referenced(
        self, keys: Collection[str], *, excluding_item_ids: Collection[int]
    ) -> set[str]:
        """Keys another, not yet purged item still points at (a text object follows its part)."""
        bases = {key.removesuffix(_TEXT_SUFFIX) for key in keys}
        if not bases:
            return set()
        excluded = list(excluding_item_ids)
        already_purged = exists().where(
            RetentionPurge.work_item_id == WorkItem.id,
            RetentionPurge.kind == PurgeKind.ARTIFACT,
        )
        found: set[str] = set()
        for chunk in _chunks(sorted(bases)):
            by_original = (
                select(WorkItem.artifact_key)
                .where(WorkItem.artifact_key.in_(chunk), ~already_purged)
                .where(*([WorkItem.id.not_in(excluded)] if excluded else []))
            )
            found.update(k for k in (await self.session.scalars(by_original)).all() if k)
            by_part = (
                select(ArtifactPart.object_key)
                .join(WorkItem, WorkItem.id == ArtifactPart.work_item_id)
                .where(ArtifactPart.object_key.in_(chunk), ~already_purged)
                .where(*([WorkItem.id.not_in(excluded)] if excluded else []))
            )
            found.update(k for k in (await self.session.scalars(by_part)).all() if k)
        return {key for key in keys if key.removesuffix(_TEXT_SUFFIX) in found}

    async def pending(self, *, limit: int) -> list[RetentionPurge]:
        stmt = (
            select(RetentionPurge)
            .where(RetentionPurge.status == PurgeStatus.PENDING)
            .order_by(RetentionPurge.created_at, RetentionPurge.id)
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def confirm(self, rows: Sequence[RetentionPurge], *, at: datetime) -> None:
        for row in rows:
            row.status = PurgeStatus.CONFIRMED
            row.confirmed_at = at
        await self.session.flush()

    async def purge_history_payloads(self, history_ids: Sequence[int], *, at: datetime) -> int:
        """Drop the payload of the given history rows; every other column stays."""
        purged = 0
        for chunk in _chunks(list(history_ids)):
            stmt = (
                update(WorkItemHistory)
                .where(
                    WorkItemHistory.id.in_(list(chunk)),
                    WorkItemHistory.purged_at.is_(None),
                )
                .values(payload=None, purged_at=at)
            )
            result = cast("CursorResult[Any]", await self.session.execute(stmt))
            purged += int(result.rowcount)
        return purged

    async def count_readings(self, item_ids: Sequence[int]) -> int:
        """How many readings a purge of ``item_ids`` would null (dry run)."""
        total = 0
        for chunk in _chunks(list(item_ids)):
            stmt = select(func.count()).where(
                and_(
                    ExtractionReading.work_item_id.in_(list(chunk)),
                    ExtractionReading.purged_at.is_(None),
                )
            )
            total += int((await self.session.execute(stmt)).scalar_one())
        return total

    async def count_adjudications(self, item_ids: Sequence[int]) -> int:
        """How many adjudications a purge of ``item_ids`` would null (dry run)."""
        total = 0
        for chunk in _chunks(list(item_ids)):
            stmt = select(func.count()).where(
                and_(
                    Adjudication.work_item_id.in_(list(chunk)),
                    Adjudication.purged_at.is_(None),
                )
            )
            total += int((await self.session.execute(stmt)).scalar_one())
        return total
