"""ENGINE_AUDIT (who controlled the engine) and ENGINE_DLQ_REPLAY (dead letters already replayed).

This module also declares the outbox index the dead-letter listing needs, so the outbox model
file stays untouched. The Alembic revision creates the same index.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk


class EngineAudit(Base):
    """Append-only: one row per control action, written in the transaction of the change."""

    __tablename__ = "engine_audit"
    __table_args__ = (Index("IX_ENGINE_AUDIT_AT", "at"),)

    id: Mapped[int] = identity_pk()
    at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    stations: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)


class EngineDlqReplay(Base):
    """A dead letter that was replayed: makes replay idempotent and hides it from the DLQ list."""

    __tablename__ = "engine_dlq_replay"
    __table_args__ = (UniqueConstraint("event_id", name="UQ_ENGINE_DLQ_REPLAY_EVENT"),)

    id: Mapped[int] = identity_pk()
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    outbox_id: Mapped[int] = mapped_column(Integer, nullable=False)
    work_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    replayed_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    audit_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("engine_audit.id", name="FK_ENGINE_DLQ_REPLAY_AUDIT"), nullable=False
    )


IX_OUTBOX_TOPIC_CREATED = Index(
    "IX_OUTBOX_TOPIC_CREATED", OutboxMessage.topic, OutboxMessage.created_at
)
