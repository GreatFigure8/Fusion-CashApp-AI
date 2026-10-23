"""What the lab needs to re-decide one past item: stored database facts plus fresh Fusion reads.

Database reads are read-only (the unit of work is never committed and the alias lookup is the
non-counting ``peek``). Fusion is reached only through ``ReadOnlyFusion``.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.repositories.lab import LabPastItemRepository
from cashapp.data.repositories.match_candidates import MatchCandidateRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.customer import CustomerResolution
from cashapp.domain.extraction import ExtractedLine
from cashapp.integrations.fusion.client import ReceiptDateBasis
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionReceipt
from cashapp.services.aliases import AliasMatch, AliasService
from cashapp.services.lab.readonly import ReadOnlyFusion
from cashapp.services.matching.decision import ReceiptMatchInputs, extraction_inputs
from cashapp.services.matching.evidence import fetch_receipt_evidence
from cashapp.services.matching.lines import APPLICABLE_LINE_KINDS, number_key
from cashapp.services.matching.receipts import ReceiptEvidence
from cashapp.services.validation import current_extraction

_CENT_FLOOR = Decimal("0.005")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PastItem:
    """The stored facts for one past work item. ``base`` is None when an input is missing."""

    item_id: int
    amount: Decimal | None
    currency: str | None
    base: ReceiptMatchInputs | None
    resolution: CustomerResolution | None
    lines: tuple[ExtractedLine, ...]
    aliases: AliasMatch | None
    stored_receipt_id: int | None
    creation_date_basis: bool
    widen_days: int


async def load_past_item(uow_factory: UowFactory, item_id: int) -> PastItem:
    """Read one item's stored extraction, customer resolution and last chosen receipt."""
    async with uow_factory() as uow:  # read-only: leaving the block rolls back
        item = await uow.repo(LabPastItemRepository).get(item_id)
        if item is None:
            return PastItem(item_id, None, None, None, None, (), None, None, False, 0)
        resolution = await uow.repo(CustomerResolutionRepository).latest_for(item_id)
        extraction = await current_extraction(uow, item_id)
        chosen = await uow.repo(MatchCandidateRepository).last_chosen(item_id)
        currency = (resolution.currency if resolution is not None else None) or item.currency
        hints: dict[str, Any] = dict(item.fix_hints or {})
        widen = int(hints.get("widen_window_days", 0) or 0)
        basis = bool(hints.get("match_on_creation_date"))
        stored_receipt_id = chosen.receipt_id if chosen is not None else None
        if (
            resolution is None
            or extraction is None
            or currency is None
            or item.payment_amount is None
            or item.payment_date is None
        ):
            return PastItem(
                item_id,
                item.payment_amount,
                currency,
                None,
                resolution,
                (),
                None,
                stored_receipt_id,
                basis,
                widen,
            )
        references, numbers, payer_name, bank_account = extraction_inputs(extraction)
        aliases = await AliasService(uow).peek(payer_name, bank_account, references)
        base = ReceiptMatchInputs(
            payment_amount=item.payment_amount,
            currency=currency,
            payment_date=item.payment_date,
            anchor=resolution.anchor_customer_number,
            related=resolution.related_customer_numbers,
            references=references,
            invoice_numbers=numbers,
            payer_bank_account=bank_account,
            fix_hints=hints,
        )
        lines = tuple(ln for ln in extraction.lines if ln.kind in APPLICABLE_LINE_KINDS)
        return PastItem(
            item_id,
            item.payment_amount,
            currency,
            base,
            resolution,
            lines,
            aliases,
            stored_receipt_id,
            basis,
            widen,
        )


@dataclass(frozen=True, slots=True)
class ReceiptPool:
    receipts: tuple[FusionReceipt, ...]
    evidence: dict[int, ReceiptEvidence]
    since_applied: bool


async def read_receipt_pool(
    fusion: ReadOnlyFusion, past: PastItem, *, window_days: int
) -> ReceiptPool:
    """One Fusion read feeds both decisions: receipts around the payment date, plus the one the
    system chose back then (so a receipt applied since is flagged, not counted as a change)."""
    base = past.base
    if base is None or past.resolution is None:
        return ReceiptPool((), {}, False)
    window = window_days + past.widen_days
    pool: dict[int, FusionReceipt] = {}
    bases: list[ReceiptDateBasis] = ["receipt_date"]
    if past.creation_date_basis:
        bases.append("creation_date")
    for basis in bases:
        found = await fusion.find_receipts(
            customer_numbers=list(past.resolution.owners()),
            date_from=_shift(base.payment_date, -window),
            date_to=_shift(base.payment_date, window),
            by=basis,
        )
        for receipt in found:
            pool.setdefault(receipt.receipt_id, receipt)
    since_applied = False
    if past.stored_receipt_id is not None:
        stored = pool.get(past.stored_receipt_id)
        if stored is None:
            try:
                stored = await fusion.get_receipt(past.stored_receipt_id)
            except FusionError:
                stored = None  # the receipt is gone; nothing to flag
            if stored is not None:
                pool[stored.receipt_id] = stored
        since_applied = stored is not None and stored.unapplied_amount <= _CENT_FLOOR
    receipts = tuple(pool.values())
    evidence = await fetch_receipt_evidence(fusion, receipts, log=logger)
    return ReceiptPool(receipts, evidence, since_applied)


def _shift(day: date, days: int) -> date:
    return day + timedelta(days=days)


def unique_numbers(lines: Sequence[ExtractedLine]) -> list[str]:
    seen: dict[str, str] = {}
    for line in lines:
        seen.setdefault(number_key(line.transaction_number), line.transaction_number.strip())
    return [n for n in seen.values() if n]
