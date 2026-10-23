"""Typed error codes for the auto-fix engine, each with its category and handling flags."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class ErrorCategory(StrEnum):
    TRANSIENT = "TRANSIENT"
    DATA = "DATA"
    AMBIGUITY = "AMBIGUITY"
    POLICY = "POLICY"
    SYSTEM = "SYSTEM"


@dataclass(frozen=True)
class ErrorSpec:
    category: ErrorCategory
    retryable: bool
    always_person: bool
    description: str


class ErrorCode(StrEnum):
    RECEIPT_NOT_YET_AVAILABLE = "RECEIPT_NOT_YET_AVAILABLE"
    RECEIPT_AMBIGUOUS = "RECEIPT_AMBIGUOUS"
    RECEIPT_RESERVED = "RECEIPT_RESERVED"
    AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
    CUSTOMER_NOT_FOUND = "CUSTOMER_NOT_FOUND"
    CUSTOMER_MULTIPLE_ACCOUNTS = "CUSTOMER_MULTIPLE_ACCOUNTS"
    INVOICE_NOT_FOUND = "INVOICE_NOT_FOUND"
    INVOICE_CLOSED = "INVOICE_CLOSED"
    INVOICE_CURRENCY_MISMATCH = "INVOICE_CURRENCY_MISMATCH"
    INVOICE_STATUS_INVALID = "INVOICE_STATUS_INVALID"
    INVALID_INVOICE_NUMBER = "INVALID_INVOICE_NUMBER"
    INVALID_DATE = "INVALID_DATE"
    INVALID_CURRENCY = "INVALID_CURRENCY"
    MISSING_PAYMENT_DATE = "MISSING_PAYMENT_DATE"
    ZERO_AMOUNT_LINE = "ZERO_AMOUNT_LINE"
    LOW_EXTRACTION_CONFIDENCE = "LOW_EXTRACTION_CONFIDENCE"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"
    LLM_REFUSAL = "LLM_REFUSAL"
    LLM_TRANSIENT = "LLM_TRANSIENT"
    UNSUPPORTED_ARTIFACT = "UNSUPPORTED_ARTIFACT"
    FUSION_OVERAPPLY = "FUSION_OVERAPPLY"
    FUSION_ALREADY_APPLIED = "FUSION_ALREADY_APPLIED"
    FUSION_LOCKED = "FUSION_LOCKED"
    FUSION_TRANSIENT = "FUSION_TRANSIENT"
    FUSION_GL_DATE = "FUSION_GL_DATE"
    FUSION_FAULT = "FUSION_FAULT"
    FUSION_DISCOUNT_REJECTED = "FUSION_DISCOUNT_REJECTED"
    FUSION_WRITE_DISABLED = "FUSION_WRITE_DISABLED"
    WRITE_BACK_FAILED = "WRITE_BACK_FAILED"
    REVERSAL_FAILED = "REVERSAL_FAILED"
    AGED_OUT = "AGED_OUT"
    PREPAYMENT = "PREPAYMENT"
    PO_SO_ERS_ONLY = "PO_SO_ERS_ONLY"
    DUAL_CURRENCY = "DUAL_CURRENCY"
    UNGROUNDED = "UNGROUNDED"
    SYSTEM_DEAD_LETTER = "SYSTEM_DEAD_LETTER"

    @property
    def spec(self) -> ErrorSpec:
        return ERROR_SPECS[self]


_TRANSIENT = frozenset(
    {
        ErrorCode.FUSION_LOCKED,
        ErrorCode.FUSION_TRANSIENT,
        ErrorCode.LLM_TRANSIENT,
        ErrorCode.RECEIPT_NOT_YET_AVAILABLE,
    }
)
_AMBIGUITY = frozenset(
    {
        ErrorCode.RECEIPT_AMBIGUOUS,
        ErrorCode.RECEIPT_RESERVED,
        ErrorCode.CUSTOMER_MULTIPLE_ACCOUNTS,
        ErrorCode.LOW_EXTRACTION_CONFIDENCE,
    }
)
_POLICY = frozenset(
    {
        ErrorCode.AMOUNT_VARIANCE,
        ErrorCode.PREPAYMENT,
        ErrorCode.PO_SO_ERS_ONLY,
        ErrorCode.DUAL_CURRENCY,
        ErrorCode.UNGROUNDED,
        ErrorCode.AGED_OUT,
        ErrorCode.FUSION_WRITE_DISABLED,
    }
)
_SYSTEM = frozenset(
    {
        ErrorCode.EXTRACTION_FAILED,
        ErrorCode.CLASSIFICATION_FAILED,
        ErrorCode.LLM_REFUSAL,
        ErrorCode.FUSION_FAULT,
        ErrorCode.WRITE_BACK_FAILED,
        ErrorCode.REVERSAL_FAILED,
        ErrorCode.SYSTEM_DEAD_LETTER,
    }
)
# RECEIPT_NOT_YET_AVAILABLE is transient but is parked and woken by the receipt watcher, never
# retried blind.
_RETRYABLE = frozenset(
    {ErrorCode.FUSION_LOCKED, ErrorCode.FUSION_TRANSIENT, ErrorCode.LLM_TRANSIENT}
)
_ALWAYS_PERSON = frozenset(
    {
        ErrorCode.PREPAYMENT,
        ErrorCode.PO_SO_ERS_ONLY,
        ErrorCode.DUAL_CURRENCY,
        ErrorCode.UNGROUNDED,
    }
)

_DESCRIPTIONS: dict[ErrorCode, str] = {
    ErrorCode.RECEIPT_NOT_YET_AVAILABLE: "No matching receipt in Fusion yet; wait for the watcher.",
    ErrorCode.RECEIPT_AMBIGUOUS: "More than one receipt qualifies for this payment.",
    ErrorCode.RECEIPT_RESERVED: "The matching receipt is reserved by another work item.",
    ErrorCode.AMOUNT_VARIANCE: "Payment and receipt amounts differ beyond tolerance.",
    ErrorCode.CUSTOMER_NOT_FOUND: "No Fusion customer could be resolved for the payer.",
    ErrorCode.CUSTOMER_MULTIPLE_ACCOUNTS: "The payer maps to more than one customer account.",
    ErrorCode.INVOICE_NOT_FOUND: "An invoice or credit memo on the remittance is not in Fusion.",
    ErrorCode.INVOICE_CLOSED: "The invoice is already closed in Fusion.",
    ErrorCode.INVOICE_CURRENCY_MISMATCH: "The invoice currency differs from the receipt currency.",
    ErrorCode.INVOICE_STATUS_INVALID: "The invoice is in a status that cannot take an application.",
    ErrorCode.INVALID_INVOICE_NUMBER: "An invoice number is malformed.",
    ErrorCode.INVALID_DATE: "A date on the remittance is invalid.",
    ErrorCode.INVALID_CURRENCY: "The currency on the remittance is invalid or ambiguous.",
    ErrorCode.MISSING_PAYMENT_DATE: "The remittance has no usable payment date.",
    ErrorCode.ZERO_AMOUNT_LINE: "A remittance line has a zero amount.",
    ErrorCode.LOW_EXTRACTION_CONFIDENCE: "Extraction confidence is below the configured threshold.",
    ErrorCode.EXTRACTION_FAILED: "Both extraction readers failed.",
    ErrorCode.CLASSIFICATION_FAILED: "The artifact could not be classified.",
    ErrorCode.LLM_REFUSAL: "The model refused to answer.",
    ErrorCode.LLM_TRANSIENT: "A transient model error (rate limit, overload, timeout).",
    ErrorCode.UNSUPPORTED_ARTIFACT: "The artifact type cannot be read.",
    ErrorCode.FUSION_OVERAPPLY: "Application exceeds the invoice balance (AR-855287).",
    ErrorCode.FUSION_ALREADY_APPLIED: "Fusion reports the receipt is already applied (AR-856102).",
    ErrorCode.FUSION_LOCKED: "Fusion row lock (ORA-00054, AR-856792).",
    ErrorCode.FUSION_TRANSIENT: "A transient Fusion failure (401, 5xx, timeout).",
    ErrorCode.FUSION_GL_DATE: "The accounting date is before the receipt GL date (AR-856089).",
    ErrorCode.FUSION_FAULT: "An unclassified Fusion fault.",
    ErrorCode.FUSION_DISCOUNT_REJECTED: "Fusion rejected the earned discount.",
    ErrorCode.FUSION_WRITE_DISABLED: "Writes to Fusion are disabled in this environment.",
    ErrorCode.WRITE_BACK_FAILED: "Posting the outcome back to Fusion failed.",
    ErrorCode.REVERSAL_FAILED: "Reversing an application in Fusion failed.",
    ErrorCode.AGED_OUT: "The item waited for a receipt past the aging limit.",
    ErrorCode.PREPAYMENT: "The payment is a prepayment; a person decides.",
    ErrorCode.PO_SO_ERS_ONLY: "The remittance references only PO, sales order or ERS numbers.",
    ErrorCode.DUAL_CURRENCY: "The payer pays in more than one currency.",
    ErrorCode.UNGROUNDED: "A value is not grounded in the remittance.",
    ErrorCode.SYSTEM_DEAD_LETTER: "The item reached the dead-letter path.",
}


def _category(code: ErrorCode) -> ErrorCategory:
    if code in _TRANSIENT:
        return ErrorCategory.TRANSIENT
    if code in _AMBIGUITY:
        return ErrorCategory.AMBIGUITY
    if code in _POLICY:
        return ErrorCategory.POLICY
    if code in _SYSTEM:
        return ErrorCategory.SYSTEM
    return ErrorCategory.DATA


ERROR_SPECS: Mapping[ErrorCode, ErrorSpec] = MappingProxyType(
    {
        code: ErrorSpec(
            category=_category(code),
            retryable=code in _RETRYABLE,
            always_person=code in _ALWAYS_PERSON,
            description=_DESCRIPTIONS[code],
        )
        for code in ErrorCode
    }
)
