"""The one extraction schema both readers fill and the adjudicator compares.

Every extracted field carries its source location and the reader's own confidence. Money is a
string in JSON (``MoneyStr``), transaction numbers are strings that refuse numeric input, and a
bare ``$`` is flagged ambiguous instead of being guessed.
"""

import re
from collections.abc import Iterator
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Final, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from cashapp.domain import extraction_text as text
from cashapp.domain.money import CurrencyCode, Money, MoneyStr

SCHEMA_VERSION: Final = "1"

_QUOTE_MAX: Final = 300


class ReaderSlot(StrEnum):
    A = "A"
    B = "B"


class ReadingStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    REFUSED = "REFUSED"


class DateKind(StrEnum):
    PAYMENT = "payment"
    ISSUE = "issue"
    ORDER = "order"
    DEPOSIT = "deposit"
    OTHER = "other"


class LineKind(StrEnum):
    INVOICE = "INVOICE"
    CREDIT_MEMO = "CREDIT_MEMO"
    UNKNOWN = "UNKNOWN"
    BANK_FEE = "BANK_FEE"
    TARIFF = "TARIFF"
    DISCOUNT = "DISCOUNT"


_NUMBERLESS_KINDS: Final = frozenset({LineKind.BANK_FEE, LineKind.TARIFF, LineKind.DISCOUNT})


def _strict_str(value: Any) -> Any:
    """Refuse non-strings: a JSON number would lose a '-1' suffix or a leading zero."""
    if not isinstance(value, str):
        raise PydanticCustomError("string_required", "A transaction number must be a string")
    return value


def _clip_quote(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _QUOTE_MAX:
        return value[:_QUOTE_MAX]
    return value


class _Strict(BaseModel):
    # Structured outputs need additionalProperties: false.
    model_config = ConfigDict(extra="forbid")


class BBox(_Strict):
    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    w: Annotated[float, Field(ge=0, le=1)]
    h: Annotated[float, Field(ge=0, le=1)]


class SourceLocation(_Strict):
    part_no: Annotated[int, Field(ge=1, description=text.DESC_PART_NO)]
    page: Annotated[int | None, Field(ge=1, description=text.DESC_PAGE)] = None
    bbox: Annotated[BBox | None, Field(description=text.DESC_BBOX)] = None
    quote: Annotated[
        str | None, BeforeValidator(_clip_quote), Field(description=text.DESC_QUOTE)
    ] = None


class Extracted[V](_Strict):
    """A value with where it was read and how sure the reader is."""

    value: Annotated[V | None, Field(description=text.DESC_VALUE)] = None
    source: Annotated[SourceLocation | None, Field(description=text.DESC_SOURCE)] = None
    confidence: Annotated[float, Field(ge=0, le=1, description=text.DESC_CONFIDENCE)]


class DateCandidate(_Strict):
    value: Annotated[date, Field(description=text.DESC_DATE_VALUE)]
    kind: Annotated[DateKind, Field(description=text.DESC_DATE_KIND)]
    source: Annotated[SourceLocation | None, Field(description=text.DESC_SOURCE)] = None
    confidence: Annotated[float, Field(ge=0, le=1, description=text.DESC_CONFIDENCE)]


class ExtractedLine(_Strict):
    line_no: Annotated[int, Field(ge=1, description=text.DESC_LINE_NO)]
    kind: Annotated[LineKind, Field(description=text.DESC_LINE_KIND)]
    transaction_number: Annotated[
        str, BeforeValidator(_strict_str), Field(description=text.DESC_TRANSACTION_NUMBER)
    ]
    amount_paid: Annotated[MoneyStr | None, Field(description=text.DESC_AMOUNT_PAID)] = None
    gross_amount: Annotated[MoneyStr | None, Field(description=text.DESC_GROSS_AMOUNT)] = None
    discount_claimed: Annotated[MoneyStr | None, Field(description=text.DESC_DISCOUNT_CLAIMED)] = (
        None
    )
    deduction: Annotated[MoneyStr | None, Field(description=text.DESC_DEDUCTION)] = None
    po_number: Annotated[str | None, Field(description=text.DESC_PO_NUMBER)] = None
    sales_order: Annotated[str | None, Field(description=text.DESC_SALES_ORDER)] = None
    ers_reference: Annotated[str | None, Field(description=text.DESC_ERS_REFERENCE)] = None
    source: Annotated[SourceLocation | None, Field(description=text.DESC_SOURCE)] = None
    confidence: Annotated[float, Field(ge=0, le=1, description=text.DESC_CONFIDENCE)]

    @model_validator(mode="after")
    def _number_present(self) -> Self:
        if not self.transaction_number.strip() and self.kind not in _NUMBERLESS_KINDS:
            raise PydanticCustomError(
                "transaction_number_required",
                "Only bank fee, tariff and discount lines may have no transaction number",
            )
        return self


# `$` with one of these directly in front names the country (US$, CA$, C$, A$, ...).
_COUNTRY_DOLLAR = re.compile(r"(?<![A-Za-z])(?:US|CA|C|A|AU|NZ|HK|S|SG|MX|R)\s?\$")
_ISO_TOKEN = re.compile(r"(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])")


def is_ambiguous_currency(raw: str | None) -> bool:
    """True for a written currency with a ``$`` and nothing that says which dollar."""
    if not raw or "$" not in raw:
        return False
    return not (_COUNTRY_DOLLAR.search(raw) or _ISO_TOKEN.search(raw))


class RemittanceExtraction(_Strict):
    payer_name: Annotated[Extracted[str], Field(description=text.DESC_PAYER_NAME)]
    payer_bank_account: Annotated[Extracted[str], Field(description=text.DESC_PAYER_BANK_ACCOUNT)]
    remittance_reference: Annotated[
        Extracted[str], Field(description=text.DESC_REMITTANCE_REFERENCE)
    ]
    payment_amount: Annotated[Extracted[MoneyStr], Field(description=text.DESC_PAYMENT_AMOUNT)]
    currency_raw: Annotated[Extracted[str], Field(description=text.DESC_CURRENCY_RAW)]
    currency: Annotated[Extracted[CurrencyCode], Field(description=text.DESC_CURRENCY)]
    currency_ambiguous: Annotated[bool, Field(description=text.DESC_CURRENCY_AMBIGUOUS)]
    dates: Annotated[list[DateCandidate], Field(description=text.DESC_DATES)]
    payment_date: Annotated[Extracted[date], Field(description=text.DESC_PAYMENT_DATE)]
    lines: Annotated[list[ExtractedLine], Field(description=text.DESC_LINES)]
    po_refs: Annotated[list[str], Field(description=text.DESC_PO_REFS)]
    sales_order_refs: Annotated[list[str], Field(description=text.DESC_SALES_ORDER_REFS)]
    ers_refs: Annotated[list[str], Field(description=text.DESC_ERS_REFS)]
    bank_fees: Annotated[list[Money], Field(description=text.DESC_BANK_FEES)]
    notes: Annotated[str | None, Field(description=text.DESC_NOTES)] = None

    @model_validator(mode="after")
    def _flag_ambiguous_currency(self) -> Self:
        # Never guess a dollar: s11 resolves it from the customer account's currency.
        if is_ambiguous_currency(self.currency_raw.value):
            self.currency_ambiguous = True
        if self.currency_ambiguous:
            self.currency = self.currency.model_copy(update={"value": None})
        return self

    def iter_fields(self) -> Iterator[tuple[str, Extracted[Any] | DateCandidate | ExtractedLine]]:
        """Every confidence-carrying field with its path, in a stable order."""
        yield "payer_name", self.payer_name
        yield "payer_bank_account", self.payer_bank_account
        yield "remittance_reference", self.remittance_reference
        yield "payment_amount", self.payment_amount
        yield "currency_raw", self.currency_raw
        yield "currency", self.currency
        yield "payment_date", self.payment_date
        for index, candidate in enumerate(self.dates):
            yield f"dates[{index}]", candidate
        for index, line in enumerate(self.lines):
            yield f"lines[{index}]", line

    def field_confidences(self) -> dict[str, float]:
        """Field path to the reader's confidence; the adjudicator averages these."""
        return {path: field.confidence for path, field in self.iter_fields()}
