"""One predicate per signal: would this signal, on its own, point at this receipt?"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from cashapp.domain.config_keys import MATCHING_DATE_WINDOW_DAYS, MATCHING_TOLERANCES
from cashapp.domain.money import money_eq
from cashapp.tools.receipt_signal_study.models import SignalName, StudyCase, StudyReceipt

WILDCARD = "*"
_MIN_TEXT_TOKEN = 3
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/.]*")
_WORD = re.compile(r"[a-z0-9]+")


def default_date_window_days() -> int:
    return int(MATCHING_DATE_WINDOW_DAYS.default)


def default_tolerances() -> dict[str, Decimal]:
    return dict(MATCHING_TOLERANCES.default)


def normalise_reference(value: str) -> str:
    """Upper-case, no whitespace, no leading zeros. The rule the receipt scorer (s13) reuses."""
    squashed = "".join(value.split()).upper()
    stripped = squashed.lstrip("0")
    return stripped or squashed


def tokenize(text: str | None) -> frozenset[str]:
    """Normalised reference-like tokens in free text (comments, addenda)."""
    if not text:
        return frozenset()
    tokens = (normalise_reference(t.strip(".-_/")) for t in _TOKEN.findall(text))
    return frozenset(t for t in tokens if len(t) >= _MIN_TEXT_TOKEN)


def name_tokens(name: str | None) -> frozenset[str]:
    """Case-folded word set of a payer name, for token-set equality."""
    return frozenset(_WORD.findall((name or "").casefold()))


def hash_account(value: str) -> str:
    """SHA-256 of the account with separators stripped; the raw value is never kept."""
    cleaned = "".join(ch for ch in value.upper() if ch.isalnum())
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SignalContext:
    date_window_days: int
    tolerances: Mapping[str, Decimal]
    related: Mapping[str, frozenset[str]]  # anchor account -> related accounts (both directions)

    def tolerance_for(self, currency: str) -> Decimal:
        found = self.tolerances.get(currency.upper())
        return found if found is not None else self.tolerances.get(WILDCARD, Decimal("0.00"))


def candidate_matches(
    signal: SignalName, case: StudyCase, receipt: StudyReceipt, ctx: SignalContext
) -> bool | None:
    """True/False when the signal can be judged for this (case, receipt); None when it cannot.

    None means the case does not carry the value, or the candidate receipt has nothing to compare.
    """
    r = receipt.receipt
    match signal:
        case SignalName.AMOUNT_EXACT:
            return money_eq(case.amount, r.amount)
        case SignalName.AMOUNT_TOLERANCE:
            return abs(case.amount - r.amount) <= ctx.tolerance_for(case.currency)
        case SignalName.DATE_RECEIPT_WINDOW:
            return abs((r.receipt_date - case.payment_date).days) <= ctx.date_window_days
        case SignalName.DATE_CREATION_WINDOW:
            return abs((r.creation_date.date() - case.payment_date).days) <= ctx.date_window_days
        case SignalName.CURRENCY:
            return r.currency.upper() == case.currency.upper()
        case SignalName.CUSTOMER_ANCHOR:
            if case.anchor_account is None or r.customer_account_number is None:
                return None
            return r.customer_account_number == case.anchor_account
        case SignalName.CUSTOMER_RELATED:
            if case.anchor_account is None or r.customer_account_number is None:
                return None
            related = ctx.related.get(case.anchor_account)
            if not related:
                return None
            return r.customer_account_number in related
        case SignalName.REMITTANCE_REFERENCE:
            if not case.reference_tokens or not receipt.reference_tokens:
                return None
            return not case.reference_tokens.isdisjoint(receipt.reference_tokens)
        case SignalName.STATEMENT_REFERENCE:
            if not case.reference_tokens or not receipt.statement_reference_tokens:
                return None
            return not case.reference_tokens.isdisjoint(receipt.statement_reference_tokens)
        case SignalName.ADDENDA_TEXT:
            terms = case.reference_tokens | case.invoice_numbers
            if not terms or not receipt.addenda_tokens:
                return None
            return not terms.isdisjoint(receipt.addenda_tokens)
        case SignalName.PAYER_NAME:
            if not case.payer_name_tokens or not receipt.payer_name_tokens:
                return None
            return case.payer_name_tokens in receipt.payer_name_tokens
        case SignalName.PAYER_BANK_ACCOUNT:
            hashes = receipt.statement.bank_account_hashes if receipt.statement else ()
            if not case.bank_account_hashes or not hashes:
                return None
            return not case.bank_account_hashes.isdisjoint(hashes)
        case SignalName.COMMENTS:
            terms = case.reference_tokens | case.invoice_numbers
            if not terms or not receipt.comment_tokens:
                return None
            return not terms.isdisjoint(receipt.comment_tokens)
        case SignalName.INVOICE_SET_OVERLAP:
            if not case.invoice_ids or not receipt.referenced_transaction_ids:
                return None
            return not case.invoice_ids.isdisjoint(receipt.referenced_transaction_ids)
