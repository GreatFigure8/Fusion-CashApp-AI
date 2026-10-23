"""The customer resolved for a work item: anchor, related accounts and the Fusion transactions."""

from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.customer import ResolutionMethod


class CustomerResolutionRow(Base):
    __tablename__ = "customer_resolution"
    __table_args__ = (Index("IX_CUSTRES_ITEM_CREATED", "work_item_id", "created_at"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_CUSTRES_WORK_ITEM"), nullable=False
    )
    anchor_customer_number: Mapped[str] = mapped_column(String(100), nullable=False)
    related_customer_numbers: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    method: Mapped[ResolutionMethod] = mapped_column(StrEnumType(ResolutionMethod), nullable=False)
    alias_ids: Mapped[list[int]] = mapped_column(JsonDoc(), nullable=False)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    transactions: Mapped[list[dict[str, Any]]] = mapped_column(JsonDoc(), nullable=False)
    flags: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    line_findings: Mapped[list[dict[str, Any]]] = mapped_column(JsonDoc(), nullable=False)
    anchor_line_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
