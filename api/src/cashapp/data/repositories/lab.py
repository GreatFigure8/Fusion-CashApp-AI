"""Queries for the matching lab. Flushes, never commits."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import exists, func, select, update

from cashapp.data.models.lab import LabCandidate, LabReplay, LabReplayItem
from cashapp.data.models.receipt_matching import MatchCandidate
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repository import BaseRepository
from cashapp.domain.lab import CandidateStatus, ReplayStatus


class LabCandidateRepository(BaseRepository[LabCandidate]):
    model = LabCandidate

    async def list_recent(
        self, limit: int, *, status: CandidateStatus | None = None
    ) -> list[LabCandidate]:
        stmt = select(LabCandidate).order_by(LabCandidate.created_at.desc(), LabCandidate.id.desc())
        if status is not None:
            stmt = stmt.where(LabCandidate.status == status)
        return [*(await self.session.scalars(stmt.limit(limit))).all()]

    async def get_for_update(self, candidate_id: int) -> LabCandidate | None:
        stmt = (
            select(LabCandidate)
            .where(LabCandidate.id == candidate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_open(self) -> int:
        stmt = select(func.count()).where(LabCandidate.status == CandidateStatus.OPEN)
        return int((await self.session.execute(stmt)).scalar_one())


class LabReplayRepository(BaseRepository[LabReplay]):
    model = LabReplay

    async def latest_for(self, candidate_id: int) -> LabReplay | None:
        stmt = (
            select(LabReplay)
            .where(LabReplay.candidate_id == candidate_id)
            .order_by(LabReplay.started_at.desc(), LabReplay.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()

    async def latest_for_candidates(self, candidate_ids: Sequence[int]) -> dict[int, LabReplay]:
        """The newest replay of each candidate that has one."""
        if not candidate_ids:
            return {}
        stmt = (
            select(LabReplay)
            .where(LabReplay.candidate_id.in_(list(candidate_ids)))
            .order_by(LabReplay.started_at, LabReplay.id)
        )
        newest: dict[int, LabReplay] = {}
        for row in (await self.session.scalars(stmt)).all():
            newest[row.candidate_id] = row  # ascending order: the last row per candidate wins
        return newest

    async def get_for_update(self, replay_id: int) -> LabReplay | None:
        stmt = (
            select(LabReplay)
            .where(LabReplay.id == replay_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def running_for(self, candidate_id: int) -> LabReplay | None:
        stmt = (
            select(LabReplay)
            .where(LabReplay.candidate_id == candidate_id, LabReplay.status == ReplayStatus.RUNNING)
            .order_by(LabReplay.id.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()

    async def mark_progress(self, replay_id: int, done: int, total: int, at: datetime) -> None:
        stmt = (
            update(LabReplay)
            .where(LabReplay.id == replay_id, LabReplay.status == ReplayStatus.RUNNING)
            .values(done=done, total=total, heartbeat_at=at)
        )
        await self.session.execute(stmt)

    async def finish(
        self,
        replay_id: int,
        status: ReplayStatus,
        summary: dict[str, Any],
        at: datetime,
        duration_ms: int,
        error: str | None,
    ) -> None:
        """Write a terminal status. Only a RUNNING replay can be finished, once."""
        stmt = (
            update(LabReplay)
            .where(LabReplay.id == replay_id, LabReplay.status == ReplayStatus.RUNNING)
            .values(
                status=status,
                finished_at=at,
                heartbeat_at=at,
                duration_ms=duration_ms,
                error=error,
                **summary,
            )
        )
        await self.session.execute(stmt)


class LabReplayItemRepository(BaseRepository[LabReplayItem]):
    model = LabReplayItem

    async def add_many(self, rows: Sequence[LabReplayItem]) -> None:
        self.session.add_all(list(rows))
        await self.session.flush()

    async def page(
        self, replay_id: int, offset: int, limit: int, *, changed_only: bool = False
    ) -> list[LabReplayItem]:
        stmt = select(LabReplayItem).where(LabReplayItem.replay_id == replay_id)
        if changed_only:
            stmt = stmt.where(LabReplayItem.changed.is_(True))
        stmt = stmt.order_by(LabReplayItem.id).offset(offset).limit(limit)
        return [*(await self.session.scalars(stmt)).all()]


class LabPastItemRepository(BaseRepository[WorkItem]):
    model = WorkItem

    async def past_items(self, since: datetime, limit: int) -> list[int]:
        """Work items that went through at least one receipt-match round, newest first."""
        had_round = exists().where(MatchCandidate.work_item_id == WorkItem.id)
        stmt = (
            select(WorkItem.id)
            .where(WorkItem.created_at >= since, had_round)
            .order_by(WorkItem.id.desc())
            .limit(limit)
        )
        return [*(await self.session.scalars(stmt)).all()]
