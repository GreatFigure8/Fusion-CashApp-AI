"""BACKLOG_BATCH: one historical-remittance import and its progress."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.backlog import BacklogSourceKind, BacklogStatus
from cashapp.domain.clock import utcnow


class BacklogBatch(Base):
    __tablename__ = "backlog_batch"
    __table_args__ = (
        UniqueConstraint("name", name="UQ_BACKLOG_BATCH_NAME"),
        Index("IX_BACKLOG_BATCH_STATUS", "status"),
    )

    id: Mapped[int] = identity_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_kind: Mapped[BacklogSourceKind] = mapped_column(
        StrEnumType(BacklogSourceKind), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    dry_run: Mapped[bool] = mapped_column(
        Boolean(create_constraint=False), nullable=False, default=False
    )
    rate_limit_per_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[BacklogStatus] = mapped_column(
        StrEnumType(BacklogStatus), nullable=False, default=BacklogStatus.IMPORTING
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    imported_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )
    import_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    promoted_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("backlog_batch.id", name="FK_BACKLOG_BATCH_PROMOTED"), nullable=True
    )
    # AUDIT is an Oracle reserved word, so the column is AUDIT_LOG.
    audit: Mapped[list[dict[str, Any]]] = mapped_column(
        "audit_log", JsonDoc(), nullable=False, default=list
    )
