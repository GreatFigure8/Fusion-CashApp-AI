"""Per-line results and the application ledger: what was planned, applied, failed or reversed."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, MoneyNumeric, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.status import LineStatus


class LineResult(Base):
    __tablename__ = "line_result"
    __table_args__ = (UniqueConstraint("work_item_id", "line_no", name="UQ_LINE_RESULT_ITEM_LINE"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_LINE_RESULT_WI"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_trx_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stated_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    balance_before: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    applied_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    residual: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    # None means planned: the apply station has not decided this line yet.
    line_status: Mapped[LineStatus | None] = mapped_column(
        StrEnumType(LineStatus, 60), nullable=True
    )
    target_status: Mapped[LineStatus | None] = mapped_column(
        StrEnumType(LineStatus, 60), nullable=True
    )
    merged_into: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[ErrorCode | None] = mapped_column(StrEnumType(ErrorCode), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


class ApplicationLedger(Base):
    __tablename__ = "application_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="UQ_APP_LEDGER_IDEM_KEY"),
        Index("IX_APP_LEDGER_ITEM_STATUS", "work_item_id", "status"),
        Index("IX_APP_LEDGER_RECEIPT", "receipt_id"),
    )

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_APP_LEDGER_WI"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_trx_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    apply_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amount: Mapped[Decimal] = mapped_column(MoneyNumeric, nullable=False)  # signed
    discount_amount: Mapped[Decimal | None] = mapped_column(MoneyNumeric, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[LedgerStatus] = mapped_column(StrEnumType(LedgerStatus), nullable=False)
    fusion_application_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[ErrorCode | None] = mapped_column(StrEnumType(ErrorCode), nullable=True)
    request: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    response_messages: Mapped[list[Any] | None] = mapped_column(JsonDoc(), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    applied_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    reversed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reversal_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )
