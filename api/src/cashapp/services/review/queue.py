"""Read models for the Review board: the queue of uploaded items and one item's review result."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from cashapp.data.models.adjudication import AdjudicationPurged
from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.artifacts import ArtifactPartRepository
from cashapp.data.repositories.review import ReviewQueueRecord, ReviewQueueRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.adjudication import AdjudicationResult
from cashapp.domain.artifacts import PartKind
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.paging import Page
from cashapp.domain.review import FieldSource
from cashapp.domain.stages import ItemState
from cashapp.domain.status import PaymentStatus
from cashapp.domain.work_item import SourceKind

_NOTE_MAX = 600
# The header fields shown on the Review board, in display order.
_RESULT_FIELDS = (
    "payer_name",
    "remittance_reference",
    "payment_amount",
    "currency",
    "payment_date",
)


@dataclass(frozen=True, slots=True)
class ReviewQueueRow:
    record: ReviewQueueRecord
    age_seconds: int


@dataclass(frozen=True, slots=True)
class ReviewField:
    field: str
    value: str | None
    source: FieldSource


@dataclass(frozen=True, slots=True)
class ReviewApplied:
    receipt_number: str
    lines: int
    residual: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ReviewRegion:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class ReviewPreview:
    artifact_key: str
    part_no: int
    kind: PartKind
    media_type: str
    page: int
    region: ReviewRegion | None


@dataclass(frozen=True, slots=True)
class ReviewResult:
    item_id: int
    status: ItemState
    payment_status: PaymentStatus | None
    fields: list[ReviewField]
    adjudication_note: str | None
    confidence: float | None
    applied: ReviewApplied | None
    preview: ReviewPreview | None


class ReviewQueueService:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or SystemClock()

    async def page(
        self, uow: UnitOfWork, offset: int, limit: int, open_only: bool
    ) -> Page[ReviewQueueRow]:
        records = await uow.repo(ReviewQueueRepository).page(offset, limit, open_only)
        now = self._clock.now()
        rows = [
            ReviewQueueRow(record, max(0, int((now - record.created_at).total_seconds())))
            for record in records.items
        ]
        return Page(items=rows, total=records.total, offset=offset, limit=limit)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def _source_of(name: str, provenance: Mapping[str, str], differed: set[str]) -> FieldSource:
    if name in differed:
        return FieldSource.A_B_DIFFERED
    match provenance.get(name):
        case "both":
            return FieldSource.A_EQ_B
        case "B":
            return FieldSource.B_ONLY
        case _:
            return FieldSource.A_ONLY


def _note(result: AdjudicationResult, missing_reader: str | None) -> str:
    if missing_reader is not None:
        other = "B" if missing_reader == "A" else "A"
        return f"Only reader {other} returned a result."
    if not result.disagreements:
        return "Both readers agreed on every field."
    text = "; ".join(f"{d.field_path}: {d.reason}" for d in result.disagreements)
    return text[:_NOTE_MAX]


def _preview(final: RemittanceExtraction | None, parts: list[ArtifactPart]) -> ReviewPreview | None:
    if not parts:
        return None
    source = final.payment_amount.source if final is not None else None
    by_no = {part.part_no: part for part in parts}
    chosen = by_no.get(source.part_no) if source is not None else None
    if source is not None and chosen is not None:
        box = source.bbox
        region = ReviewRegion(box.x, box.y, box.w, box.h) if box is not None else None
        page = source.page or 1
        return ReviewPreview(
            chosen.object_key, chosen.part_no, chosen.kind, chosen.media_type, page, region
        )
    first = parts[0]
    return ReviewPreview(first.object_key, first.part_no, first.kind, first.media_type, 1, None)


class ReviewResultService:
    async def result(self, uow: UnitOfWork, item_id: int) -> ReviewResult | None:
        """The review result of an uploaded item; ``None`` for an unknown or non-uploaded one."""
        item = await uow.work_items.get(item_id)
        if item is None or item.source_kind is not SourceKind.MANUAL:
            return None

        adjudication = await uow.repo(AdjudicationRepository).latest_for(item_id)
        fields: list[ReviewField] = []
        note: str | None = None
        confidence: float | None = None
        final: RemittanceExtraction | None = None
        if adjudication is not None:
            confidence = float(adjudication.confidence)
            try:
                result = adjudication.result()
            except AdjudicationPurged:
                result = None
            if result is not None:
                final = result.final
                differed = {d.field_path for d in result.disagreements}
                for name in _RESULT_FIELDS:
                    extracted = getattr(final, name)
                    fields.append(
                        ReviewField(
                            name,
                            _text(extracted.value),
                            _source_of(name, result.provenance, differed),
                        )
                    )
                missing = adjudication.missing_reader
                note = _note(result, missing.value if missing is not None else None)

        parts = await uow.repo(ArtifactPartRepository).for_item(item_id)
        return ReviewResult(
            item_id=item.id,
            status=item.state,
            payment_status=item.payment_status,
            fields=fields,
            adjudication_note=note,
            confidence=confidence,
            applied=await self._applied(uow, item_id, item.currency),
            preview=_preview(final, parts),
        )

    @staticmethod
    async def _applied(uow: UnitOfWork, item_id: int, currency: str | None) -> ReviewApplied | None:
        ledger = await uow.repo(ApplicationLedgerRepository).applied_for(item_id)
        if not ledger:
            return None
        receipt = next((row.receipt_number for row in ledger if row.receipt_number), None)
        lines = {row.line_no for row in ledger}
        residual = Decimal("0.00")
        for line in await uow.repo(LineResultRepository).for_item(item_id):
            if line.residual is not None:
                residual += line.residual
        return ReviewApplied(
            receipt_number=receipt or str(ledger[0].receipt_id),
            lines=len(lines),
            residual=residual,
            currency=currency or "",
        )
