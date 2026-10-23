"""Learned payer aliases: one row per alias key (name, bank account or reference pattern)."""

from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import UtcDateTime, identity_pk


class PayerAlias(Base):
    __tablename__ = "payer_alias"

    id: Mapped[int] = identity_pk()
    payer_name_norm: Mapped[str | None] = mapped_column(String(500), nullable=True)
    payer_bank_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reference_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_account_number: Mapped[str] = mapped_column(String(100), nullable=False)
    # No FK: the retention purge may remove work items.
    learned_from_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    retired_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retire_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
