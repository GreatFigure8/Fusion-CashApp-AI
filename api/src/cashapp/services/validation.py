"""Validate: code checks on the adjudicated extraction. Pure; no LLM, no Fusion, no I/O.

Header versus line totals are a flag, never a failure. Everything that would send a bad
extraction on to Fusion is a typed error, and all issues are collected in one pass. Messages
carry codes, field paths and amounts only: never the payer name or artifact text.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final

from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine, LineKind, RemittanceExtraction
from cashapp.domain.iso4217 import is_iso_4217
from cashapp.domain.money import money_eq
from cashapp.domain.status import InfoFlag

MAX_PAST_DAYS: Final = 400
MAX_FUTURE_DAYS: Final = 60
INVOICE_NUMBER_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_/\.]{0,39}$")
SCI_NOTATION_RE: Final = re.compile(r"^[+-]?\d+(\.\d+)?[eE][+-]?\d+$")
INVOICE_LIKE_KINDS: Final[frozenset[LineKind]] = frozenset(
    {LineKind.INVOICE, LineKind.CREDIT_MEMO, LineKind.UNKNOWN}
)
VALIDATION_ERROR_PRECEDENCE: Final[tuple[ErrorCode, ...]] = (
    ErrorCode.PO_SO_ERS_ONLY,
    ErrorCode.INVALID_INVOICE_NUMBER,
    ErrorCode.MISSING_PAYMENT_DATE,
    ErrorCode.INVALID_DATE,
    ErrorCode.INVALID_CURRENCY,
    ErrorCode.ZERO_AMOUNT_LINE,
)

_ZERO: Final = Decimal("0")


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: ErrorCode
    field_path: str
    message: str
    line_no: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "field_path": self.field_path,
            "message": self.message,
            "line_no": self.line_no,
        }


def _money_str(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    flags: frozenset[InfoFlag]
    errors: tuple[ValidationIssue, ...]
    cleaned: RemittanceExtraction
    notices: tuple[ValidationIssue, ...] = ()
    duplicate_transaction_numbers: tuple[str, ...] = ()
    header_amount: Decimal | None = None
    line_sum: Decimal | None = None
    currency: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def _sorted_flags(self) -> list[str]:
        return sorted(flag.value for flag in self.flags)

    def to_detail(self) -> dict[str, Any]:
        return {
            "issues": [issue.to_dict() for issue in self.errors],
            "notices": [issue.to_dict() for issue in self.notices],
            "flags": self._sorted_flags(),
        }

    def to_history_payload(self, *, adjudication_id: int) -> dict[str, Any]:
        return {
            "adjudication_id": adjudication_id,
            "flags": self._sorted_flags(),
            "notices": [issue.to_dict() for issue in self.notices],
            "duplicate_transaction_numbers": list(self.duplicate_transaction_numbers),
            "header_amount": _money_str(self.header_amount),
            "line_sum": _money_str(self.line_sum),
            "lines_in": len(self.cleaned.lines) + len(self.notices),
            "lines_kept": len(self.cleaned.lines),
        }


def _is_zero(line: ExtractedLine) -> bool:
    return line.amount_paid is not None and money_eq(line.amount_paid, _ZERO)


def clean(extraction: RemittanceExtraction) -> RemittanceExtraction:
    """Trim transaction numbers and drop zero-amount lines; line numbers are kept as they are."""
    lines = [
        line.model_copy(update={"transaction_number": line.transaction_number.strip()})
        for line in extraction.lines
        if not _is_zero(line)
    ]
    return extraction.model_copy(update={"lines": lines})


def _number_is_valid(number: str) -> bool:
    if not number or SCI_NOTATION_RE.match(number):
        return False
    return bool(INVOICE_NUMBER_RE.match(number))


def _signed_amount(line: ExtractedLine) -> Decimal:
    amount = line.amount_paid if line.amount_paid is not None else _ZERO
    return -abs(amount) if line.kind is LineKind.CREDIT_MEMO else amount


def validate(extraction: RemittanceExtraction, today: date) -> ValidationReport:
    flags: set[InfoFlag] = set()
    errors: list[tuple[int, int, ValidationIssue]] = []
    notices: list[ValidationIssue] = []

    def add_error(issue: ValidationIssue, line_index: int = -1) -> None:
        errors.append((VALIDATION_ERROR_PRECEDENCE.index(issue.code), line_index, issue))

    header = extraction.payment_amount.value
    lines = extraction.lines

    # 1. Header against lines: a flag, never an error.
    line_sum: Decimal | None = None
    amounted = [
        line for line in lines if line.kind in INVOICE_LIKE_KINDS and line.amount_paid is not None
    ]
    if amounted:
        line_sum = sum((_signed_amount(line) for line in amounted), _ZERO)
        if header is not None and not money_eq(header, line_sum):
            flags.add(InfoFlag.PAYMENT_HEADER_LINE_MISMATCH)

    # 2. Invoice numbers and duplicates.
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    has_invoice_like = False
    for index, line in enumerate(lines):
        number = line.transaction_number.strip()
        invoice_like = line.kind in INVOICE_LIKE_KINDS
        if not invoice_like and not number:
            continue
        if not _number_is_valid(number):
            add_error(
                ValidationIssue(
                    ErrorCode.INVALID_INVOICE_NUMBER,
                    f"lines[{index}].transaction_number",
                    f"Line {line.line_no} has a malformed transaction number",
                    line.line_no,
                ),
                index,
            )
            continue
        if invoice_like:
            has_invoice_like = True
            key = number.upper()
            if key not in seen:
                seen[key] = number
            elif seen[key] not in duplicates:
                duplicates.append(seen[key])

    # 3. Dates.
    payment_date = extraction.payment_date.value
    if payment_date is None:
        add_error(
            ValidationIssue(ErrorCode.MISSING_PAYMENT_DATE, "payment_date", "No payment date")
        )
    elif (today - payment_date).days > MAX_PAST_DAYS or (
        payment_date - today
    ).days > MAX_FUTURE_DAYS:
        add_error(
            ValidationIssue(
                ErrorCode.INVALID_DATE,
                "payment_date",
                f"Payment date is outside {MAX_PAST_DAYS} days back / {MAX_FUTURE_DAYS} ahead",
            )
        )

    # 4. Currency. Ambiguous or absent is deferred to customer resolution.
    code = extraction.currency.value
    currency: str | None = None
    if code is not None and not extraction.currency_ambiguous:
        if is_iso_4217(code):
            currency = code
        else:
            add_error(
                ValidationIssue(
                    ErrorCode.INVALID_CURRENCY, "currency", f"{code} is not an ISO 4217 code"
                )
            )

    # 5. Zero amounts: per-line notices, plus one item-level error when everything is zero.
    zero_indexes = [i for i, line in enumerate(lines) if _is_zero(line)]
    for index in zero_indexes:
        notices.append(
            ValidationIssue(
                ErrorCode.ZERO_AMOUNT_LINE,
                f"lines[{index}].amount_paid",
                f"Line {lines[index].line_no} has a zero amount and was dropped",
                lines[index].line_no,
            )
        )
    if header is not None and money_eq(header, _ZERO) and len(zero_indexes) == len(lines):
        add_error(
            ValidationIssue(ErrorCode.ZERO_AMOUNT_LINE, "", "The payment and every line are zero")
        )

    # 6. References only.
    has_refs = bool(
        extraction.po_refs
        or extraction.sales_order_refs
        or extraction.ers_refs
        or any(line.po_number or line.sales_order or line.ers_reference for line in lines)
    )
    if has_refs and not has_invoice_like:
        add_error(
            ValidationIssue(
                ErrorCode.PO_SO_ERS_ONLY,
                "",
                "Only PO, sales order or ERS references; no invoice numbers",
            )
        )

    errors.sort(key=lambda entry: (entry[0], entry[1]))
    return ValidationReport(
        flags=frozenset(flags),
        errors=tuple(entry[2] for entry in errors),
        cleaned=clean(extraction),
        notices=tuple(notices),
        duplicate_transaction_numbers=tuple(duplicates),
        header_amount=header,
        line_sum=line_sum,
        currency=currency,
    )


def first_error(report: ValidationReport) -> ErrorCode | None:
    present = {issue.code for issue in report.errors}
    for code in VALIDATION_ERROR_PRECEDENCE:
        if code in present:
            return code
    return None


async def current_extraction(uow: UnitOfWork, item_id: int) -> RemittanceExtraction | None:
    """The cleaned view of the latest adjudication, for stations that read after validate."""
    row = await uow.repo(AdjudicationRepository).latest_for(item_id)
    if row is None or row.final is None:
        return None
    return clean(RemittanceExtraction.model_validate(row.final))
