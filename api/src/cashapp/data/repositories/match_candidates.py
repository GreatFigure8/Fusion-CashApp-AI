"""Queries over MATCH_CANDIDATE. Flushes, never commits."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select

from cashapp.data.models.receipt_matching import MatchCandidate
from cashapp.data.repository import BaseRepository
from cashapp.domain.clock import utcnow
from cashapp.domain.receipt_matching import DecidedBy


@dataclass(frozen=True, slots=True)
class CandidateRow:
    receipt_id: int
    receipt_number: str | None
    qualifies: bool
    score: float
    signals: Mapping[str, float]
    reasons: Sequence[str]
    chosen: bool
    decided_by: DecidedBy
    customer_account_number: str | None
    currency: str | None
    receipt_date: date | None
    unapplied_amount: Decimal | None


class MatchCandidateRepository(BaseRepository[MatchCandidate]):
    model = MatchCandidate

    async def _latest_attempt(self, item_id: int) -> int:
        stmt = select(func.max(MatchCandidate.attempt)).where(
            MatchCandidate.work_item_id == item_id
        )
        latest = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(latest) if latest is not None else 0

    async def next_attempt(self, item_id: int) -> int:
        """The next round number for the item, starting at 1."""
        return await self._latest_attempt(item_id) + 1

    async def add_round(
        self,
        item_id: int,
        attempt: int,
        rows: Sequence[CandidateRow],
        *,
        now: datetime | None = None,
    ) -> list[MatchCandidate]:
        created_at = now if now is not None else utcnow()
        entities = [
            MatchCandidate(
                work_item_id=item_id,
                attempt=attempt,
                receipt_id=row.receipt_id,
                receipt_number=row.receipt_number,
                qualifies=row.qualifies,
                score=row.score,
                signals=dict(row.signals),
                chosen=row.chosen,
                decided_by=row.decided_by,
                created_at=created_at,
                reasons=list(row.reasons),
                customer_account_number=row.customer_account_number,
                currency=row.currency,
                receipt_date=row.receipt_date,
                unapplied_amount=row.unapplied_amount,
            )
            for row in rows
        ]
        self.session.add_all(entities)
        await self.session.flush()
        return entities

    async def for_item(self, item_id: int, *, attempt: int | None = None) -> list[MatchCandidate]:
        """One round (the latest by default), chosen first then by score."""
        round_no = attempt if attempt is not None else await self._latest_attempt(item_id)
        if round_no < 1:
            return []
        stmt = (
            select(MatchCandidate)
            .where(MatchCandidate.work_item_id == item_id, MatchCandidate.attempt == round_no)
            .order_by(MatchCandidate.chosen.desc(), MatchCandidate.score.desc(), MatchCandidate.id)
        )
        return [*(await self.session.execute(stmt)).scalars().all()]

    async def last_chosen(self, item_id: int) -> MatchCandidate | None:
        """The newest CHOSEN row across all rounds."""
        stmt = (
            select(MatchCandidate)
            .where(MatchCandidate.work_item_id == item_id, MatchCandidate.chosen.is_(True))
            .order_by(MatchCandidate.attempt.desc(), MatchCandidate.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()
