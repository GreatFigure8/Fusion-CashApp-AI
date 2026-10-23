"""API contracts for the item view: detail, history and search."""

import logging
from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ValidationError

from cashapp.api.schemas.locks import LockInfoOut
from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.artifacts import ArtifactPart
from cashapp.data.models.customer_resolution import CustomerResolutionRow
from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.domain.adjudication import Disagreement
from cashapp.domain.artifacts import PartKind
from cashapp.domain.customer import ResolutionMethod
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ReaderSlot, ReadingStatus, RemittanceExtraction
from cashapp.domain.money import CurrencyCode, MoneyStr
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import LineStatus, PaymentStatus
from cashapp.domain.work_item import ActorKind, HistoryAction
from cashapp.services.flow_query import (
    ItemDetailData,
    ReceiptRef,
    SearchHit,
    fusion_result_code,
)

logger = logging.getLogger(__name__)


def _extraction_or_none(raw: dict[str, Any] | None) -> RemittanceExtraction | None:
    """Stored model output as the typed extraction; an unreadable document is dropped (logged)."""
    if raw is None:
        return None
    try:
        return RemittanceExtraction.model_validate(raw)
    except ValidationError:
        logger.warning("stored extraction no longer validates against the schema")
        return None


class ItemOut(BaseModel):
    id: int
    stage: Stage
    state: ItemState
    payment_status: PaymentStatus | None
    payer_name: str | None
    amount: MoneyStr | None
    currency: CurrencyCode | None
    payment_date: date | None
    customer_account_number: str | None
    received_at: datetime
    updated_at: datetime
    attempts: int
    last_error_code: ErrorCode | None
    escalation_summary: str | None
    info_flags: list[str]
    version: int

    @classmethod
    def from_item(cls, item: WorkItem) -> Self:
        return cls(
            id=item.id,
            stage=item.stage,
            state=item.state,
            payment_status=item.payment_status,
            payer_name=item.payer_name,
            amount=item.payment_amount,
            currency=item.currency,
            payment_date=item.payment_date,
            customer_account_number=item.customer_account_number,
            received_at=item.created_at,
            updated_at=item.updated_at,
            attempts=item.attempts,
            last_error_code=item.last_error_code,
            escalation_summary=item.escalation_summary,
            info_flags=[str(flag) for flag in item.info_flags],
            version=item.version,
        )


class ReadingOut(BaseModel):
    status: ReadingStatus
    model_id: str
    attempt: int
    output: RemittanceExtraction | None
    created_at: datetime

    @classmethod
    def from_row(cls, row: ExtractionReading) -> Self:
        return cls(
            status=row.status,
            model_id=row.model_id,
            attempt=row.attempt,
            output=_extraction_or_none(row.output),
            created_at=row.created_at,
        )


class ExtractionOut(BaseModel):
    """The adjudicated extraction and where each value came from.

    ``provenance`` maps a field path (``payer_name``, ``lines[2]``) to ``A``, ``B``, ``both`` or
    ``human``. Line entries are keyed by the line's index in ``final.lines``.
    """

    final: RemittanceExtraction | None
    provenance: dict[str, str]
    disagreements: list[Disagreement]
    confidence: float | None
    reader_a: ReadingOut | None
    reader_b: ReadingOut | None
    missing_reader: ReaderSlot | None
    purged: bool

    @classmethod
    def from_data(cls, data: ItemDetailData) -> Self:
        adjudication = data.adjudication
        final: RemittanceExtraction | None = None
        provenance: dict[str, str] = {}
        disagreements: list[Disagreement] = []
        if adjudication is not None:
            final = _extraction_or_none(adjudication.final)
            provenance = _flatten_provenance(adjudication, final)
            disagreements = _disagreements(adjudication)
        reader_a = data.readings.get(ReaderSlot.A)
        reader_b = data.readings.get(ReaderSlot.B)
        return cls(
            final=final,
            provenance=provenance,
            disagreements=disagreements,
            confidence=None if adjudication is None else float(adjudication.confidence),
            reader_a=None if reader_a is None else ReadingOut.from_row(reader_a),
            reader_b=None if reader_b is None else ReadingOut.from_row(reader_b),
            missing_reader=None if adjudication is None else adjudication.missing_reader,
            purged=adjudication is not None and adjudication.purged_at is not None,
        )


def _flatten_provenance(
    adjudication: Adjudication, final: RemittanceExtraction | None
) -> dict[str, str]:
    stored = adjudication.provenance
    flat: dict[str, str] = {str(k): str(v) for k, v in dict(stored.get("fields", {})).items()}
    index_of = {line.line_no: index for index, line in enumerate(final.lines)} if final else {}
    for row in stored.get("lines", []):
        index = index_of.get(int(row["line_no"]))
        if index is not None:
            flat[f"lines[{index}]"] = str(row["source"])
    return flat


def _disagreements(adjudication: Adjudication) -> list[Disagreement]:
    found: list[Disagreement] = []
    for row in adjudication.disagreements or []:
        try:
            found.append(Disagreement.model_validate(row))
        except ValidationError:
            logger.warning("a stored disagreement no longer validates")
    return found


class PartOut(BaseModel):
    part_no: int
    kind: PartKind
    media_type: str
    purged: bool

    @classmethod
    def from_row(cls, row: ArtifactPart) -> Self:
        return cls(
            part_no=row.part_no,
            kind=row.kind,
            media_type=row.media_type,
            purged=row.purged_at is not None,
        )


class LineOut(BaseModel):
    line_no: int
    transaction_number: str | None
    stated_amount: MoneyStr | None
    fusion_balance: MoneyStr | None
    applied_amount: MoneyStr | None
    line_status: LineStatus | None
    fusion_result_code: str | None


class ResolutionOut(BaseModel):
    anchor_customer_number: str
    related_customer_numbers: list[str]
    method: ResolutionMethod
    currency: CurrencyCode | None
    flags: list[str]

    @classmethod
    def from_row(cls, row: CustomerResolutionRow) -> Self:
        return cls(
            anchor_customer_number=row.anchor_customer_number,
            related_customer_numbers=[str(n) for n in row.related_customer_numbers],
            method=row.method,
            currency=row.currency,
            flags=[str(flag) for flag in row.flags],
        )


class ReceiptOut(BaseModel):
    receipt_id: int
    receipt_number: str
    decided_by: str
    score: float | None
    reservation_status: str | None

    @classmethod
    def from_ref(cls, ref: ReceiptRef) -> Self:
        return cls(
            receipt_id=ref.receipt_id,
            receipt_number=ref.receipt_number,
            decided_by=ref.decided_by,
            score=ref.score,
            reservation_status=ref.reservation_status,
        )


class ItemDetailOut(BaseModel):
    item: ItemOut
    lock: LockInfoOut | None
    extraction: ExtractionOut
    parts: list[PartOut]
    lines: list[LineOut]
    resolution: ResolutionOut | None
    receipt: ReceiptOut | None

    @classmethod
    def from_data(cls, data: ItemDetailData) -> Self:
        return cls(
            item=ItemOut.from_item(data.item),
            lock=LockInfoOut.from_info(data.lock),
            extraction=ExtractionOut.from_data(data),
            parts=[PartOut.from_row(p) for p in data.parts],
            lines=[
                LineOut(
                    line_no=line.line_no,
                    transaction_number=line.transaction_number,
                    stated_amount=line.stated_amount,
                    fusion_balance=line.balance_before,
                    applied_amount=line.applied_amount,
                    line_status=line.line_status,
                    fusion_result_code=fusion_result_code(line, ledger),
                )
                for line, ledger in data.lines
            ],
            resolution=None if data.resolution is None else ResolutionOut.from_row(data.resolution),
            receipt=None if data.receipt is None else ReceiptOut.from_ref(data.receipt),
        )


class HistoryRowOut(BaseModel):
    id: int
    at: datetime
    action: HistoryAction
    actor_kind: ActorKind
    actor_id: str
    actor_name: str
    from_stage: Stage | None
    to_stage: Stage | None
    from_state: ItemState | None
    to_state: ItemState | None
    error_code: ErrorCode | None
    reasoning: str | None
    payload: dict[str, Any] | None
    purged: bool

    @classmethod
    def from_row(cls, row: WorkItemHistory) -> Self:
        purged = row.purged_at is not None
        return cls(
            id=row.id,
            at=row.at,
            action=row.action,
            actor_kind=row.actor_kind,
            actor_id=row.actor_id,
            actor_name=row.actor_name,
            from_stage=row.from_stage,
            to_stage=row.to_stage,
            from_state=row.from_state,
            to_state=row.to_state,
            error_code=row.error_code,
            reasoning=row.reasoning,
            payload=None if purged else row.payload,
            purged=purged,
        )


class HistoryOut(BaseModel):
    items: list[HistoryRowOut]
    total: int

    @classmethod
    def from_rows(cls, rows: list[WorkItemHistory], *, total: int) -> Self:
        return cls(items=[HistoryRowOut.from_row(r) for r in rows], total=total)


class SearchHitOut(BaseModel):
    item_id: int
    kind: Literal["item", "receipt", "invoice"]
    match: str
    stage: Stage
    state: ItemState

    @classmethod
    def from_hit(cls, hit: SearchHit) -> Self:
        return cls(
            item_id=hit.item_id, kind=hit.kind, match=hit.match, stage=hit.stage, state=hit.state
        )


class SearchOut(BaseModel):
    hits: list[SearchHitOut]
