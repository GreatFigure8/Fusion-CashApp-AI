"""The one matcher entry point: the pipeline runners and the matching lab both decide here.

Pure: no database, no bus, no Fusion calls. Callers read what Fusion and the database hold and
pass it in; this module only decides. It composes the scorer (``score_candidates``) and the line
planner (``plan_lines``) with the decision logic that used to sit inline in the stage runners.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from cashapp.domain.extraction import ExtractedLine, LineKind, RemittanceExtraction
from cashapp.domain.receipt_matching import DecidedBy
from cashapp.integrations.fusion.models import (
    FusionApplication,
    FusionReceipt,
    FusionTransaction,
)
from cashapp.services.matching.lines import LinePlan, index_transactions, plan_lines
from cashapp.services.matching.receipts import (
    Candidate,
    MatchContext,
    Outcome,
    ReceiptEvidence,
    ScoredCandidates,
    score_candidates,
)

if TYPE_CHECKING:
    from cashapp.services.aliases import AliasMatch
    from cashapp.services.config_groups import MatchingConfig
    from cashapp.services.matching.discount import DiscountContext

_CENT_FLOOR: Final = Decimal("0.005")

HUMAN_NOT_FOUND: Final = "not_found"
HUMAN_CURRENCY_MISMATCH: Final = "currency_mismatch"
HUMAN_NO_UNAPPLIED: Final = "no_unapplied"


def _text(value: str | None) -> str | None:
    stripped = value.strip() if value else ""
    return stripped or None


def extraction_inputs(
    extraction: RemittanceExtraction | None,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None, str | None]:
    """References, invoice/credit-memo numbers, payer name and payer bank account."""
    if extraction is None:
        return (), (), None, None
    reference = _text(extraction.remittance_reference.value)
    numbers = tuple(
        dict.fromkeys(
            line.transaction_number.strip()
            for line in extraction.lines
            if line.kind in (LineKind.INVOICE, LineKind.CREDIT_MEMO)
            and line.transaction_number.strip()
        )
    )
    return (
        (reference,) if reference else (),
        numbers,
        _text(extraction.payer_name.value),
        _text(extraction.payer_bank_account.value),
    )


@dataclass(frozen=True, slots=True)
class ReceiptMatchInputs:
    payment_amount: Decimal
    currency: str
    payment_date: date
    anchor: str
    related: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    invoice_numbers: tuple[str, ...] = ()
    payer_bank_account: str | None = None
    fix_hints: Mapping[str, Any] = MappingProxyType({})
    # receipt_id -> amount already applied from it to this remittance (partial-apply resume)
    resume_applied: Mapping[int, Decimal] = MappingProxyType({})
    human_receipt_id: int | None = None

    def context(self) -> MatchContext:
        return MatchContext(
            payment_amount=self.payment_amount,
            currency=self.currency,
            payment_date=self.payment_date,
            anchor=self.anchor,
            related=self.related,
            references=self.references,
            invoice_numbers=self.invoice_numbers,
            payer_bank_account=self.payer_bank_account,
            fix_hints=self.fix_hints,
            resume_applied=self.resume_applied,
        )


@dataclass(frozen=True, slots=True)
class ReceiptMatchDecision:
    scored: ScoredCandidates
    winner: Candidate | None
    decided_by: DecidedBy
    rule: str | None
    human_problem: str | None
    # What the decision means for the item: a human problem counts as a variance (the runner
    # raises AMOUNT_VARIANCE for it).
    outcome: Outcome


def decide_receipt(
    inputs: ReceiptMatchInputs,
    receipts: Sequence[FusionReceipt],
    config: MatchingConfig,
    *,
    aliases: AliasMatch | None = None,
    evidence: Mapping[int, ReceiptEvidence] | None = None,
) -> ReceiptMatchDecision:
    """Score the receipts and resolve a person's chosen receipt, if one was given."""
    scored = score_candidates(inputs.context(), list(receipts), config, aliases, evidence=evidence)
    winner, decided_by, rule = scored.winner, DecidedBy.SYSTEM, scored.rule
    human_problem: str | None = None
    human_id = inputs.human_receipt_id
    if human_id is not None:
        winner = next((c for c in scored.candidates if c.receipt.receipt_id == human_id), None)
        decided_by, rule = DecidedBy.HUMAN, "human"
        if winner is None:
            human_problem = HUMAN_NOT_FOUND
        elif winner.receipt.currency.upper() != inputs.currency.upper():
            human_problem = HUMAN_CURRENCY_MISMATCH
        elif winner.receipt.unapplied_amount <= _CENT_FLOOR:
            human_problem = HUMAN_NO_UNAPPLIED
    if human_problem is not None:
        outcome: Outcome = "variance"
    elif human_id is not None:
        outcome = "matched"
    else:
        outcome = scored.outcome
    return ReceiptMatchDecision(
        scored=scored,
        winner=winner,
        decided_by=decided_by,
        rule=rule,
        human_problem=human_problem,
        outcome=outcome,
    )


def index_line_transactions(
    found: Sequence[FusionTransaction],
    lines: Sequence[ExtractedLine],
    owners: Collection[str],
) -> tuple[dict[str, FusionTransaction], frozenset[str]]:
    """One transaction per number, plus the numbers that stayed ambiguous."""
    return index_transactions(found, lines, owners)


def decide_lines(
    lines: Sequence[ExtractedLine],
    transactions: Mapping[str, FusionTransaction],
    owners: Collection[str],
    receipt_remaining: Decimal,
    existing: Sequence[FusionApplication],
    payment_currency: str,
    config: MatchingConfig,
    *,
    ambiguous: Collection[str] = (),
    header_amount: Decimal | None = None,
    discount: DiscountContext | None = None,
) -> LinePlan:
    """Plan the applications with the currency's configured tolerance."""
    return plan_lines(
        lines,
        transactions,
        receipt_remaining,
        existing,
        payment_currency,
        header_amount=header_amount,
        tolerance=config.tolerance_for(payment_currency),
        owners=owners,
        ambiguous=ambiguous,
        discount=discount,
    )


@dataclass(frozen=True, slots=True)
class MatchDecision:
    receipt: ReceiptMatchDecision
    lines: LinePlan | None = None
