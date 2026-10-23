"""The normalised parts of a work item's artifact (the objects live in Object Storage)."""

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.artifacts import PartKind


class ArtifactPart(Base):
    __tablename__ = "artifact_part"
    __table_args__ = (UniqueConstraint("work_item_id", "part_no", name="UQ_ARTIFACT_PART_ITEM_NO"),)

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int] = mapped_column(
        ForeignKey("work_item.id", name="FK_ARTIFACT_PART_ITEM"), nullable=False
    )
    part_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[PartKind] = mapped_column(StrEnumType(PartKind), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # len(text) when a sibling text object exists, else None.
    text_preview_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
