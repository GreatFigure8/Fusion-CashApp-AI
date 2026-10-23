"""One row per reader attempt: what each extraction reader returned, kept for the adjudicator."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ReaderSlot, ReadingStatus


class ExtractionReading(Base):
    __tablename__ = "extraction_reading"
    __table_args__ = (Index("IX_EXTRACTION_READING_ITEM", "work_item_id", "reader", "attempt"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_EXTRACTION_READING_WI"), nullable=False
    )
    reader: Mapped[ReaderSlot] = mapped_column(StrEnumType(ReaderSlot), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[ReadingStatus] = mapped_column(StrEnumType(ReadingStatus), nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JsonDoc(), nullable=True)
    error_code: Mapped[ErrorCode | None] = mapped_column(StrEnumType(ErrorCode), nullable=True)
    # Codes and counts only: never prompt, artifact or model output text.
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
