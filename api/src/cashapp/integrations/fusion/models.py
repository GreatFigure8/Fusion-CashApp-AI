"""Frozen value types exchanged with Fusion. Money is `Decimal`; no float anywhere."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cashapp.integrations.fusion.errors import FusionFault


class TransactionKind(StrEnum):
    INVOICE = "INVOICE"
    CREDIT_MEMO = "CREDIT_MEMO"


@dataclass(frozen=True, slots=True)
class FusionTransaction:
    customer_trx_id: int
    number: str
    kind: TransactionKind
    balance: Decimal  # credit memos negative
    original_amount: Decimal  # credit memos negative
    currency: str
    status: str
    bill_to_customer_number: str | None = None
    bill_to_site: str | None = None
    business_unit: str | None = None
    payment_terms: str | None = None


@dataclass(frozen=True, slots=True)
class FusionReceipt:
    receipt_id: int
    receipt_number: str
    amount: Decimal
    unapplied_amount: Decimal
    currency: str
    customer_account_number: str | None
    receipt_date: date
    creation_date: datetime  # tz-aware UTC
    status: str
    state: str
    remittance_references: tuple[str, ...] = ()
    comments: str | None = None


@dataclass(frozen=True, slots=True)
class FusionApplication:
    application_id: int
    receipt_id: int
    customer_trx_id: int
    amount_applied: Decimal
    apply_date: date
    status: str  # "APP"; reversed applications are kept with their status


@dataclass(frozen=True, slots=True)
class FusionCustomerSite:
    site_number: str
    purpose: str | None = None
    location: str | None = None
    address: str | None = None


@dataclass(frozen=True, slots=True)
class FusionCustomer:
    account_number: str
    name: str
    currency_codes: tuple[str, ...] = ()
    sites: tuple[FusionCustomerSite, ...] = ()


RelationshipDirection = Literal["INBOUND", "OUTBOUND"]


@dataclass(frozen=True, slots=True)
class CustomerRelationship:
    account_number: str  # the queried account
    related_account_number: str
    related_account_name: str | None
    directions: frozenset[RelationshipDirection]


@dataclass(frozen=True, slots=True)
class FusionMessage:
    code: str | None
    severity: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ApplyRequest:
    receipt_id: int
    customer_trx_id: int
    amount_applied: Decimal  # signed: negative for credit memos
    receipt_currency: str
    application_date: date
    accounting_date: date
    discount_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ApplyResult:
    ok: bool
    application_id: int | None
    fault: FusionFault | None
    raw_messages: tuple[FusionMessage, ...]
    receipt_id: int  # the id matched on; the response ReceiptId is nil


@dataclass(frozen=True, slots=True)
class UnapplyRequest:
    receipt_id: int
    application_id: int
    reversal_gl_date: date
    reason: str


@dataclass(frozen=True, slots=True)
class UnapplyResult:
    ok: bool
    fault: FusionFault | None
    raw_messages: tuple[FusionMessage, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    receipt_id: int
    attachment_id: str | None
    filename: str
