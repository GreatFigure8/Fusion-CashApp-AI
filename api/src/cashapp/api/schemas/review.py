"""API contracts for the Review board and the failed-receipt upload. Never ORM rows."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from cashapp.domain.money import MoneyStr
from cashapp.domain.review import FieldSource, UploadStatus
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.services.review.queue import ReviewQueueRow, ReviewResult
from cashapp.services.review.upload import (
    Quota,
    StageBatchResult,
    UploadBatchResult,
    UploadFileResult,
)


class UploadFileResultOut(BaseModel):
    filename: str
    status: UploadStatus
    item_id: int | None
    message: str

    @classmethod
    def from_result(cls, result: UploadFileResult) -> Self:
        return cls(
            filename=result.filename,
            status=result.status,
            item_id=result.item_id,
            message=result.message,
        )


class QuotaOut(BaseModel):
    used: int
    limit: int

    @classmethod
    def from_quota(cls, quota: Quota) -> Self:
        return cls(used=quota.used, limit=quota.limit)


class UploadResultOut(BaseModel):
    files: list[UploadFileResultOut]
    quota: QuotaOut

    @classmethod
    def from_batch(cls, batch: UploadBatchResult) -> Self:
        return cls(
            files=[UploadFileResultOut.from_result(f) for f in batch.files],
            quota=QuotaOut.from_quota(batch.quota),
        )


class StagedUploadsOut(BaseModel):
    upload_ids: list[str]
    files: list[UploadFileResultOut]
    quota: QuotaOut

    @classmethod
    def from_batch(cls, batch: StageBatchResult) -> Self:
        return cls(
            upload_ids=batch.upload_ids,
            files=[UploadFileResultOut.from_result(f) for f in batch.files],
            quota=QuotaOut.from_quota(batch.quota),
        )


class ReviewQueueRowOut(BaseModel):
    item_id: int
    filename: str | None
    stage: Stage
    status: ItemState
    payment_status: PaymentStatus | None
    age_seconds: int
    created_at: datetime
    confidence: float | None

    @classmethod
    def from_row(cls, row: ReviewQueueRow) -> Self:
        record = row.record
        return cls(
            item_id=record.item_id,
            filename=record.filename,
            stage=record.stage,
            status=record.state,
            payment_status=record.payment_status,
            age_seconds=row.age_seconds,
            created_at=record.created_at,
            confidence=record.confidence,
        )


class ReviewQueuePage(BaseModel):
    items: list[ReviewQueueRowOut]
    total: int
    offset: int
    limit: int


class ReviewFieldOut(BaseModel):
    field: str
    value: str | None
    source: FieldSource


class AppliedOut(BaseModel):
    receipt_number: str
    lines: int
    residual: MoneyStr
    currency: str


class RegionOut(BaseModel):
    x: float
    y: float
    w: float
    h: float


class PreviewOut(BaseModel):
    artifact_key: str
    part_no: int
    page: int
    region: RegionOut | None


class ReviewResultOut(BaseModel):
    item_id: int
    status: ItemState
    payment_status: PaymentStatus | None
    fields: list[ReviewFieldOut]
    adjudication_note: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)
    applied: AppliedOut | None
    preview: PreviewOut | None

    @classmethod
    def from_result(cls, result: ReviewResult) -> Self:
        applied = result.applied
        preview = result.preview
        return cls(
            item_id=result.item_id,
            status=result.status,
            payment_status=result.payment_status,
            fields=[
                ReviewFieldOut(field=f.field, value=f.value, source=f.source) for f in result.fields
            ],
            adjudication_note=result.adjudication_note,
            confidence=result.confidence,
            applied=AppliedOut(
                receipt_number=applied.receipt_number,
                lines=applied.lines,
                residual=applied.residual,
                currency=applied.currency,
            )
            if applied is not None
            else None,
            preview=PreviewOut(
                artifact_key=preview.artifact_key,
                part_no=preview.part_no,
                page=preview.page,
                region=RegionOut(
                    x=preview.region.x, y=preview.region.y, w=preview.region.w, h=preview.region.h
                )
                if preview.region is not None
                else None,
            )
            if preview is not None
            else None,
        )
