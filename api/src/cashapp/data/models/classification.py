"""One row per classification decision, by the model or by a person."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.classification import ClassificationOrigin
from cashapp.domain.clock import utcnow


class Classification(Base):
    __tablename__ = "classification"
    __table_args__ = (Index("IX_CLASSIFICATION_ITEM_AT", "work_item_id", "created_at"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_CLASSIFICATION_WI"), nullable=False
    )
    is_remittance: Mapped[bool] = mapped_column(Boolean(create_constraint=False), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3, asdecimal=False), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    origin: Mapped[ClassificationOrigin] = mapped_column(
        StrEnumType(ClassificationOrigin), nullable=False
    )
    decided_by: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
