"""Earned early-payment discount: the pure rule, the terms loader and the audit payload.

CLAUDE.md: "Never invent a discount. Take one only when the remittance references it and the
payment terms earned it." `earned_discount` returns a discount only when the customer claimed
one, the invoice's terms still allow it on the payment date, the computed amount agrees with the
claim and the stated cash plus the discount reconcile to the invoice balance. Every other path
returns a typed `DiscountReason`, so the decision is auditable from the item's history.

Terms semantics (tier days counted from the invoice date to the payment date, inclusive) are
UNVERIFIED until the s39 live probe confirms them against a non-production pod.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from cashapp.domain.money import to_money
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import (
    DiscountTier,
    FusionTransaction,
    PaymentTerms,
    TransactionKind,
)

_ZERO = Decimal("0.00")
_HUNDRED = Decimal(100)


class DiscountReason(StrEnum):
    EARNED = "earned"
    NOT_CLAIMED = "not-claimed"  # remittance doesn't reference a discount on this line
    INVALID_CLAIM = "invalid-claim"  # claimed <= 0 or >= balance
    NOT_AN_INVOICE = "not-an-invoice"  # credit memos never take a discount
    NO_STATED_AMOUNT = "no-stated-amount"
    NO_TERMS = "no-terms"  # transaction has no terms, or terms not found
    TERMS_HAVE_NO_DISCOUNT = "terms-have-no-discount"
    NO_TRANSACTION_DATE = "no-transaction-date"
    PAYMENT_BEFORE_INVOICE = "payment-before-invoice"
    NOT_EARNED = "not-earned"  # paid after every tier's days
    CLAIM_MISMATCH = "claim-mismatch"  # no earned tier's computed discount is near the claim
    AMOUNTS_DONT_RECONCILE = "amounts-dont-reconcile"  # stated + discount is not near balance
    RECEIPT_REMAINING_SHORT = "receipt-remaining-short"  # set by plan_lines (cash would be capped)
    DISABLED = "disabled"  # set by plan_lines when discount.enabled is false


@dataclass(frozen=True, slots=True)
class DiscountDecision:
    amount: Decimal | None  # None => no discount (treat as short pay)
    reason: DiscountReason
    tier: DiscountTier | None = None
    computed: Decimal | None = None
    claimed: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DiscountContext:
    payment_date: date
    terms: Mapping[str, PaymentTerms]  # keyed by FusionTransaction.payment_terms
    tolerance: Decimal


class DiscountStep(Protocol):
    """The slice of s15's `LineStep` the audit reads."""

    @property
    def line_number(self) -> int: ...

    @property
    def discount_amount(self) -> Decimal | None: ...

    @property
    def discount_reason(self) -> DiscountReason | None: ...


def earned_discount(
    transaction: FusionTransaction,
    terms: PaymentTerms | None,
    payment_date: date,
    claimed: Decimal | None,
    stated_amount: Decimal | None,
    tolerance: Decimal,
) -> DiscountDecision:
    """Decide the discount for one line; the first failing check returns its reason."""
    if claimed is None:
        return DiscountDecision(None, DiscountReason.NOT_CLAIMED)
    if transaction.kind is not TransactionKind.INVOICE:
        return DiscountDecision(None, DiscountReason.NOT_AN_INVOICE, claimed=claimed)
    if stated_amount is None:
        return DiscountDecision(None, DiscountReason.NO_STATED_AMOUNT, claimed=claimed)
    balance = transaction.balance
    if claimed <= _ZERO or claimed >= balance:
        return DiscountDecision(None, DiscountReason.INVALID_CLAIM, claimed=claimed)
    if terms is None:
        return DiscountDecision(None, DiscountReason.NO_TERMS, claimed=claimed)
    if not terms.discount_tiers:
        return DiscountDecision(None, DiscountReason.TERMS_HAVE_NO_DISCOUNT, claimed=claimed)
    if transaction.transaction_date is None:
        return DiscountDecision(None, DiscountReason.NO_TRANSACTION_DATE, claimed=claimed)
    elapsed = (payment_date - transaction.transaction_date).days
    if elapsed < 0:
        return DiscountDecision(None, DiscountReason.PAYMENT_BEFORE_INVOICE, claimed=claimed)
    earned = sorted((t for t in terms.discount_tiers if elapsed <= t.days), key=lambda t: t.days)
    if not earned:
        return DiscountDecision(None, DiscountReason.NOT_EARNED, claimed=claimed)
    chosen: DiscountTier | None = None
    computed = _ZERO
    for tier in earned:
        candidate = to_money(balance * tier.percent / _HUNDRED)
        if abs(candidate - claimed) <= tolerance:
            chosen, computed = tier, candidate
            break
    if chosen is None:
        return DiscountDecision(None, DiscountReason.CLAIM_MISMATCH, claimed=claimed)
    amount = min(claimed, computed)
    if abs(stated_amount + amount - balance) > tolerance:
        return DiscountDecision(
            None,
            DiscountReason.AMOUNTS_DONT_RECONCILE,
            tier=chosen,
            computed=computed,
            claimed=claimed,
        )
    return DiscountDecision(
        amount, DiscountReason.EARNED, tier=chosen, computed=computed, claimed=claimed
    )


async def load_payment_terms(fusion: FusionClient, names: Iterable[str]) -> dict[str, PaymentTerms]:
    """Fetch each distinct terms name once. Unknown terms and non-retryable errors are omitted
    (those lines become short pays); a retryable `FusionError` propagates so the item retries."""
    found: dict[str, PaymentTerms] = {}
    for name in dict.fromkeys(names):
        try:
            terms = await fusion.get_payment_terms(name)
        except FusionError as exc:
            if exc.retryable:
                raise
            continue
        if terms is not None:
            found[name] = terms
    return found


def discount_audit(steps: Sequence[DiscountStep]) -> list[dict[str, str | int | None]]:
    """Per-line payload for the DECISION history row: why a discount was or wasn't taken."""
    audit: list[dict[str, str | int | None]] = []
    for step in steps:
        reason = step.discount_reason
        if reason is None:
            continue
        decision: DiscountDecision | None = getattr(step, "discount_decision", None)
        amount = step.discount_amount
        audit.append(
            {
                "line": step.line_number,
                "reason": reason.value,
                "claimed": None
                if decision is None or decision.claimed is None
                else str(decision.claimed),
                "computed": None
                if decision is None or decision.computed is None
                else str(decision.computed),
                "tier_days": None
                if decision is None or decision.tier is None
                else decision.tier.days,
                "tier_percent": None
                if decision is None or decision.tier is None
                else str(decision.tier.percent),
                "amount": None if amount is None else str(amount),
            }
        )
    return audit
