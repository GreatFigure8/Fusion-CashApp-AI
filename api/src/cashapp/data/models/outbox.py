"""Transactional outbox: events are written in the same transaction as the state change."""

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.work_item import PRIORITY_LIVE


class OutboxMessage(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("IX_OUTBOX_PENDING", "published_at", "not_before", "priority"),)

    id: Mapped[int] = identity_pk()
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    msg_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=PRIORITY_LIVE)
    # NOT NULL: Oracle B-tree indexes skip all-null keys. emit() sets it to now when no delay.
    not_before: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
