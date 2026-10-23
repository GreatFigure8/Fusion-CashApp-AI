"""The Fusion receipt watcher's high-water mark: one row per Fusion pod."""

from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime
from cashapp.domain.clock import utcnow


class ReceiptWatermark(Base):
    __tablename__ = "receipt_watermark"

    pod: Mapped[str] = mapped_column(String(100), primary_key=True)
    high_water_mark: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    # {"<receipt_id>": "<creation ISO>"} for receipts already emitted inside the overlap window.
    seen_at_mark: Mapped[dict[str, str]] = mapped_column(JsonDoc(), nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )
