"""The event queue: one row per message published to the bus, consumed with a lease."""

from datetime import datetime
from typing import Any

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.work_item import PRIORITY_LIVE


class BusMessage(Base):
    """A message waiting for (or already past) its consumer.

    A consumer claims a row by setting `leased_until`; `consumed_at` is set when it finishes. A
    row whose lease ran out and that was never consumed is claimed again (a crash is harmless:
    every handler is idempotent). Consumed rows are kept for the history and purged by retention.
    """

    __tablename__ = "bus_message"
    __table_args__ = (Index("IX_BUS_MESSAGE_READY", "topic", "consumed_at", "priority", "id"),)

    id: Mapped[int] = identity_pk()
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    msg_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=PRIORITY_LIVE)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    leased_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
