"""Payment and line statuses, failure precedence, info flags and the roll-up.

This module is the ONLY place these status strings are defined. Matcher, API, UI and reporting
import them from here.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from cashapp.domain.money import money_eq


class PaymentStatus(StrEnum):
    PAYMENT_SUCCESS = "payment-success"
    PAYMENT_LESS_THAN_TOTAL_DUE_SUCCESS = "payment-less-than-total-due-success"
    PAYMENT_MORE_THAN_TOTAL_DUE_SUCCESS = "payment-more-than-total-due-success"
    PAYMENT_PREVIOUSLY_APPLIED = "payment-previously-applied"
    INVOICE_NOT_FOUND = "invoice-not-found"
    CUSTOMER_NOT_FOUND = "customer-not-found"
    MISSING_PAYMENT_DATE = "missing-payment-date"
    RECEIPT_NOT_FOUND = "receipt-not-found"
    ZERO_AMOUNT = "zero-amount"
    PAYMENT_APPLY_FAILED_SYSTEM = "payment-apply-failed-system"
    PAYMENT_APPLY_FAILED_RECEIPT_CLOSED = "payment-apply-failed-receipt-closed"
    PAYMENT_APPLY_FAILED_ZERO_BALANCE = "payment-apply-failed-zero-balance"


SUCCESS_STATUSES: frozenset[PaymentStatus] = frozenset(
    {
        PaymentStatus.PAYMENT_SUCCESS,
        PaymentStatus.PAYMENT_LESS_THAN_TOTAL_DUE_SUCCESS,
        PaymentStatus.PAYMENT_MORE_THAN_TOTAL_DUE_SUCCESS,
        PaymentStatus.PAYMENT_PREVIOUSLY_APPLIED,
    }
)

# When several failures apply, the earliest in this tuple is the one reported.
PAYMENT_FAILURE_PRECEDENCE: tuple[PaymentStatus, ...] = (
    PaymentStatus.INVOICE_NOT_FOUND,
    PaymentStatus.CUSTOMER_NOT_FOUND,
    PaymentStatus.MISSING_PAYMENT_DATE,
    PaymentStatus.RECEIPT_NOT_FOUND,
    PaymentStatus.ZERO_AMOUNT,
    PaymentStatus.PAYMENT_APPLY_FAILED_RECEIPT_CLOSED,
    PaymentStatus.PAYMENT_APPLY_FAILED_ZERO_BALANCE,
    PaymentStatus.PAYMENT_APPLY_FAILED_SYSTEM,
)


class LineStatus(StrEnum):
    ALLOCATION_APPLIED = "allocation-applied"
    ALLOCATION_APPLIED_SHORT_PAY = "allocation-applied-short-pay"
    ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION = "allocation-applied-less-than-instruction"
    ALLOCATION_APPLIED_WITH_DISCOUNT = "allocation-applied-with-discount"
    ALLOCATION_PREVIOUSLY_APPLIED = "allocation-previously-applied"
    ALLOCATION_INVOICE_NOT_FOUND = "allocation-invoice-not-found"
    ALLOCATION_CUSTOMER_NOT_FOUND = "allocation-customer-not-found"
    ALLOCATION_NO_REMAINING_BALANCE = "allocation-no-remaining-balance"
    ALLOCATION_ZERO_AMOUNT = "allocation-zero-amount"
    ALLOCATION_MISSING_PAYMENT_DATE = "allocation-missing-payment-date"
    ALLOCATION_NO_RECEIPT_MATCH = "allocation-no-receipt-match"
    ALLOCATION_APPLY_FAILED = "allocation-apply-failed"
    ALLOCATION_REVERSED = "allocation-reversed"
    ALLOCATION_DRY_RUN = "allocation-dry-run"


APPLIED_LINE_STATUSES: frozenset[LineStatus] = frozenset(
    {
        LineStatus.ALLOCATION_APPLIED,
        LineStatus.ALLOCATION_APPLIED_SHORT_PAY,
        LineStatus.ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION,
        LineStatus.ALLOCATION_APPLIED_WITH_DISCOUNT,
    }
)


class InfoFlag(StrEnum):
    PAYMENT_HEADER_LINE_MISMATCH = "payment-header-line-mismatch"
    MULTIPLE_ACCOUNTS_SAME_RECEIPT = "multiple-accounts-same-receipt"
    DISCOUNT_REJECTED_BY_FUSION = "discount-rejected-by-fusion"
    CURRENCY_RESOLVED_FROM_CUSTOMER = "currency-resolved-from-customer"
    ALIAS_USED = "alias-used"


@dataclass(frozen=True)
class HeaderResult:
    customer_found: bool
    payment_date_present: bool
    receipt_found: bool
    applied_total: Decimal  # sum actually applied (zero when nothing)
    total_due: Decimal  # sum the remittance said it was paying
    receipt_closed: bool = False
    dry_run: bool = False


_LINE_FAILURES: dict[LineStatus, PaymentStatus] = {
    LineStatus.ALLOCATION_INVOICE_NOT_FOUND: PaymentStatus.INVOICE_NOT_FOUND,
    LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND: PaymentStatus.CUSTOMER_NOT_FOUND,
    LineStatus.ALLOCATION_MISSING_PAYMENT_DATE: PaymentStatus.MISSING_PAYMENT_DATE,
    LineStatus.ALLOCATION_NO_RECEIPT_MATCH: PaymentStatus.RECEIPT_NOT_FOUND,
    LineStatus.ALLOCATION_APPLY_FAILED: PaymentStatus.PAYMENT_APPLY_FAILED_SYSTEM,
}


def roll_up(header: HeaderResult, lines: Sequence[LineStatus]) -> PaymentStatus:
    """Derive the payment status strictly from the header and line results."""
    if lines and all(line is LineStatus.ALLOCATION_PREVIOUSLY_APPLIED for line in lines):
        return PaymentStatus.PAYMENT_PREVIOUSLY_APPLIED

    any_applied = any(
        line in APPLIED_LINE_STATUSES or (line is LineStatus.ALLOCATION_DRY_RUN and header.dry_run)
        for line in lines
    )
    if any_applied and header.receipt_found and header.customer_found:
        if money_eq(header.applied_total, header.total_due):
            return PaymentStatus.PAYMENT_SUCCESS
        if header.applied_total < header.total_due:
            return PaymentStatus.PAYMENT_LESS_THAN_TOTAL_DUE_SUCCESS
        return PaymentStatus.PAYMENT_MORE_THAN_TOTAL_DUE_SUCCESS

    candidates: set[PaymentStatus] = set()
    if not header.customer_found:
        candidates.add(PaymentStatus.CUSTOMER_NOT_FOUND)
    if not header.payment_date_present:
        candidates.add(PaymentStatus.MISSING_PAYMENT_DATE)
    if not header.receipt_found:
        candidates.add(PaymentStatus.RECEIPT_NOT_FOUND)
    if header.receipt_closed:
        candidates.add(PaymentStatus.PAYMENT_APPLY_FAILED_RECEIPT_CLOSED)

    for line in lines:
        mapped = _LINE_FAILURES.get(line)
        if mapped is not None:
            candidates.add(mapped)
        elif line is LineStatus.ALLOCATION_DRY_RUN and not header.dry_run:
            candidates.add(PaymentStatus.PAYMENT_APPLY_FAILED_SYSTEM)

    if lines:
        if all(line is LineStatus.ALLOCATION_ZERO_AMOUNT for line in lines):
            candidates.add(PaymentStatus.ZERO_AMOUNT)
        non_zero = [line for line in lines if line is not LineStatus.ALLOCATION_ZERO_AMOUNT]
        if non_zero and all(
            line is LineStatus.ALLOCATION_NO_REMAINING_BALANCE for line in non_zero
        ):
            candidates.add(PaymentStatus.PAYMENT_APPLY_FAILED_ZERO_BALANCE)
    elif money_eq(header.total_due, Decimal(0)):
        candidates.add(PaymentStatus.ZERO_AMOUNT)

    for status in PAYMENT_FAILURE_PRECEDENCE:
        if status in candidates:
            return status
    # Nothing applied and no failure to report (for example every line was reversed).
    return PaymentStatus.PAYMENT_APPLY_FAILED_SYSTEM


class ExceptionSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ExceptionInfo:
    type: str
    error_code: str
    reason: str
    severity: ExceptionSeverity
    title: str
    detail: str
    error_details: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """All seven keys are always present."""
        return {
            "type": self.type,
            "error_code": self.error_code,
            "reason": self.reason,
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "error_details": list(self.error_details),
        }
