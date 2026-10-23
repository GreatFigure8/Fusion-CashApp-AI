"""The work item (one artifact moving down the assembly line) and its history."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CHAR, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, MoneyNumeric, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.domain.work_item import (
    PRIORITY_LIVE,
    ActorKind,
    FixHints,
    HistoryAction,
    HumanHints,
    SourceKind,
)


class WorkItem(Base):
    __tablename__ = "work_item"
    __table_args__ = (
        UniqueConstraint("content_hash", name="UQ_WORK_ITEM_CONTENT_HASH"),
        Index("IX_WORK_ITEM_STAGE_STATE", "stage", "state"),
        Index("IX_WORK_ITEM_STATE_AWAITING", "state", "awaiting_since"),
        Index("IX_WORK_ITEM_LOCK_OWNER", "lock_owner"),
        Index("IX_WORK_ITEM_PARENT_ID", "parent_id"),
    )

    id: Mapped[int] = identity_pk()
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_item.id", name="FK_WORK_ITEM_PARENT"), nullable=True
    )
    source_kind: Mapped[SourceKind] = mapped_column(StrEnumType(SourceKind), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    artifact_key: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stage: Mapped[Stage] = mapped_column(StrEnumType(Stage), nullable=False)
    state: Mapped[ItemState] = mapped_column(
        StrEnumType(ItemState), nullable=False, default=ItemState.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[ErrorCode | None] = mapped_column(StrEnumType(ErrorCode), nullable=True)
    last_error_detail: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    escalation_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Claim fields: written by the stage runner (s03) only.
    claim_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    # Lock fields: written by the locking service (s40) only.
    lock_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lock_owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lock_acquired_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    payer_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    payment_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_status: Mapped[PaymentStatus | None] = mapped_column(
        StrEnumType(PaymentStatus), nullable=True
    )
    info_flags: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False, default=list)
    human_hints: Mapped[HumanHints | None] = mapped_column(JsonDoc(), nullable=True)
    fix_hints: Mapped[FixHints | None] = mapped_column(JsonDoc(), nullable=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=PRIORITY_LIVE)
    awaiting_since: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )

    # Optimistic concurrency: an UPDATE of a stale row raises StaleDataError.
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class WorkItemHistory(Base):
    __tablename__ = "work_item_history"
    __table_args__ = (Index("IX_WIH_ITEM_AT", "work_item_id", "at"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_WIH_WORK_ITEM"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    actor_kind: Mapped[ActorKind] = mapped_column(StrEnumType(ActorKind), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[HistoryAction] = mapped_column(StrEnumType(HistoryAction), nullable=False)
    from_stage: Mapped[Stage | None] = mapped_column(StrEnumType(Stage), nullable=True)
    to_stage: Mapped[Stage | None] = mapped_column(StrEnumType(Stage), nullable=True)
    from_state: Mapped[ItemState | None] = mapped_column(StrEnumType(ItemState), nullable=True)
    to_state: Mapped[ItemState | None] = mapped_column(StrEnumType(ItemState), nullable=True)
    error_code: Mapped[ErrorCode | None] = mapped_column(StrEnumType(ErrorCode), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
