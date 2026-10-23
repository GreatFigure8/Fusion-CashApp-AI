"""Receipt reservations and the per-candidate audit trail of receipt matching."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, MoneyNumeric, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.receipt_matching import DecidedBy, ReservationStatus


class ReceiptReservation(Base):
    """A receipt held for one work item. At most one ACTIVE row per receipt."""

    __tablename__ = "receipt_reservation"
    __table_args__ = (
        # Function-based unique index: only ACTIVE rows compete for a receipt.
        Index(
            "UX_RR_ACTIVE_RECEIPT",
            text("CASE WHEN STATUS = 'ACTIVE' THEN RECEIPT_ID END"),
            unique=True,
        ),
        Index("IX_RR_ITEM_STATUS", "work_item_id", "status"),
    )

    id: Mapped[int] = identity_pk()
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_RR_WORK_ITEM"), nullable=False
    )
    status: Mapped[ReservationStatus] = mapped_column(
        StrEnumType(ReservationStatus), nullable=False
    )
    reserved_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class MatchCandidate(Base):
    """One receipt the matcher looked at in one round, with its signals."""

    __tablename__ = "match_candidate"
    __table_args__ = (Index("IX_MC_ITEM_ATTEMPT", "work_item_id", "attempt"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_MC_WORK_ITEM"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qualifies: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    signals: Mapped[dict[str, float]] = mapped_column(JsonDoc(), nullable=False)
    chosen: Mapped[bool] = mapped_column(
        Boolean(create_constraint=False), nullable=False, default=False
    )
    decided_by: Mapped[DecidedBy] = mapped_column(
        StrEnumType(DecidedBy), nullable=False, default=DecidedBy.SYSTEM
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    reasons: Mapped[list[Any] | None] = mapped_column(JsonDoc(), nullable=True)
    customer_account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    receipt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    unapplied_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
