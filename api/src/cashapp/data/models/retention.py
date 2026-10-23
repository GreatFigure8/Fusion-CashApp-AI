"""RETENTION_PURGE: the pending/confirmed marker that makes an artifact purge crash-safe."""

from datetime import datetime

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.retention import PurgeKind, PurgeStatus


class RetentionPurge(Base):
    __tablename__ = "retention_purge"
    __table_args__ = (
        UniqueConstraint("work_item_id", "kind", name="UQ_RETENTION_PURGE_ITEM_KIND"),
        Index("IX_RETENTION_PURGE_STATUS", "status", "created_at"),
    )

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_RETENTION_PURGE_ITEM"), nullable=False
    )
    kind: Mapped[PurgeKind] = mapped_column(StrEnumType(PurgeKind), nullable=False)
    status: Mapped[PurgeStatus] = mapped_column(StrEnumType(PurgeStatus, 20), nullable=False)
    object_keys: Mapped[list[str]] = mapped_column(JsonDoc(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
