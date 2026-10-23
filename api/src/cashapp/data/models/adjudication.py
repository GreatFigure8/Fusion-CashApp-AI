"""The adjudicated extraction of a work item: the final values and where each one came from."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.adjudication import AdjudicationOrigin, AdjudicationResult
from cashapp.domain.clock import utcnow
from cashapp.domain.extraction import ReaderSlot


class AdjudicationPurged(Exception):  # noqa: N818 - pinned name
    """The final extraction was removed by the retention purge."""

    def __init__(self, adjudication_id: int) -> None:
        super().__init__(f"adjudication {adjudication_id} payload was purged")
        self.adjudication_id = adjudication_id


class Adjudication(Base):
    __tablename__ = "adjudication"
    __table_args__ = (Index("IX_ADJUDICATION_ITEM", "work_item_id", "created_at"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_ADJUDICATION_WI"), nullable=False
    )
    origin: Mapped[AdjudicationOrigin] = mapped_column(
        StrEnumType(AdjudicationOrigin), nullable=False
    )
    model_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    reading_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_reading.id", name="FK_ADJUDICATION_RA"), nullable=True
    )
    reading_b_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_reading.id", name="FK_ADJUDICATION_RB"), nullable=True
    )
    missing_reader: Mapped[ReaderSlot | None] = mapped_column(
        StrEnumType(ReaderSlot), nullable=True
    )
    final: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JsonDoc(), nullable=False)
    disagreements: Mapped[list[Any] | None] = mapped_column(JsonDoc(), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4, asdecimal=True), nullable=False)
    edited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)

    def result(self) -> AdjudicationResult:
        """The stored result; raises ``AdjudicationPurged`` once the payload was purged."""
        if self.final is None:
            raise AdjudicationPurged(self.id)
        return AdjudicationResult.from_stored(
            final=self.final,
            provenance=self.provenance,
            disagreements=self.disagreements,
            confidence=self.confidence,
        )
