"""The matching lab: candidate configs, their replays and the per-item replay results."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, BigInteger, Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, MoneyNumeric, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.lab import CandidateStatus, ReplayStatus


class LabCandidate(Base):
    """A proposed change to the matching keys, kept apart from live config until promoted."""

    __tablename__ = "lab_candidate"
    __table_args__ = (Index("IX_LAB_CAND_STATUS_AT", "status", "created_at"),)

    id: Mapped[int] = identity_pk()
    changes: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_key_versions: Mapped[dict[str, int]] = mapped_column(JsonDoc(), nullable=False)
    base_values: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(StrEnumType(CandidateStatus), nullable=False)
    created_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    closed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    promoted_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


class LabReplay(Base):
    """One run of a candidate against past items. STALE is computed on read, never stored."""

    __tablename__ = "lab_replay"
    __table_args__ = (
        Index("IX_LAB_REPLAY_CAND", "candidate_id", "started_at"),
        Index("IX_LAB_REPLAY_STATUS_FIN", "status", "finished_at"),
    )

    id: Mapped[int] = identity_pk()
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("lab_candidate.id", name="FK_LAB_REPLAY_CAND"), nullable=False
    )
    status: Mapped[ReplayStatus] = mapped_column(StrEnumType(ReplayStatus), nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    live_version: Mapped[int] = mapped_column(Integer, nullable=False)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    newly_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    newly_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    newly_ambiguous: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    money_by_currency: Mapped[list[Any]] = mapped_column(JsonDoc(), nullable=False, default=list)
    started_by: Mapped[str] = mapped_column(String(256), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    runner_boot_id: Mapped[str] = mapped_column(String(36), nullable=False)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class LabReplayItem(Base):
    """One past work item evaluated under live and candidate config. No FK to WORK_ITEM."""

    __tablename__ = "lab_replay_item"
    __table_args__ = (
        Index("IX_LAB_RI_REPLAY_CHANGED", "replay_id", "changed"),
        Index("IX_LAB_RI_WORK_ITEM", "work_item_id"),
    )

    id: Mapped[int] = identity_pk()
    replay_id: Mapped[int] = mapped_column(
        ForeignKey("lab_replay.id", name="FK_LAB_RI_REPLAY"), nullable=False
    )
    work_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    before_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    after_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    before_receipt_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    after_receipt_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    changed: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False)
    since_applied: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
