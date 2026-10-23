"""One row per notification attempt: sent, failed or suppressed. Never holds message bodies."""

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        Index("IX_NOTIFICATION_LOG_KIND_AT", "kind", "sent_at"),
        Index("IX_NOTIFICATION_LOG_AT", "sent_at"),
    )

    id: Mapped[int] = identity_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # email, teams or none
    recipients: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    subject: Mapped[str] = mapped_column(String(400), nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # sent, failed, suppressed
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
