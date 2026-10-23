"""Records for the receipt-signal study (tooling types, not API contracts)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from cashapp.integrations.fusion import FusionApplication, FusionReceipt


class SignalName(StrEnum):
    AMOUNT_EXACT = "amount_exact"
    AMOUNT_TOLERANCE = "amount_tolerance"
    DATE_RECEIPT_WINDOW = "date_receipt_window"
    DATE_CREATION_WINDOW = "date_creation_window"
    CURRENCY = "currency"
    CUSTOMER_ANCHOR = "customer_anchor"
    CUSTOMER_RELATED = "customer_related"
    REMITTANCE_REFERENCE = "remittance_reference"
    STATEMENT_REFERENCE = "statement_reference"
    ADDENDA_TEXT = "addenda_text"
    PAYER_NAME = "payer_name"
    PAYER_BANK_ACCOUNT = "payer_bank_account"
    COMMENTS = "comments"
    INVOICE_SET_OVERLAP = "invoice_set_overlap"


SIGNALS: tuple[SignalName, ...] = tuple(SignalName)

# Signals that need bank statement lines, read through the s32 BIP report.
STATEMENT_SIGNALS: tuple[SignalName, ...] = (
    SignalName.STATEMENT_REFERENCE,
    SignalName.ADDENDA_TEXT,
    SignalName.PAYER_NAME,
    SignalName.PAYER_BANK_ACCOUNT,
)

# Reconstructing the remittance from the truth receipt makes these tautological in Fusion-only mode.
CIRCULAR_IN_FUSION_MODE: frozenset[SignalName] = frozenset(
    {SignalName.AMOUNT_EXACT, SignalName.DATE_RECEIPT_WINDOW, SignalName.CURRENCY}
)

CaseSource = Literal["fusion", "prior"]


@dataclass(frozen=True, slots=True)
class StatementSignals:
    """What the bank statement lines of one receipt say. Bank accounts are SHA-256 hashes."""

    receipt_id: int
    statement_references: tuple[str, ...] = ()
    addenda_texts: tuple[str, ...] = ()
    payer_names: tuple[str, ...] = ()
    bank_account_hashes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StudyReceipt:
    """A candidate receipt with everything the predicates look at, resolved once."""

    receipt: FusionReceipt
    statement: StatementSignals | None
    comment_tokens: frozenset[str]  # normalised tokens of the receipt comments
    addenda_tokens: frozenset[str]  # normalised tokens of the statement addenda
    reference_tokens: frozenset[str]  # normalised remittance references
    statement_reference_tokens: frozenset[str]
    payer_name_tokens: frozenset[frozenset[str]]  # one token set per statement payer name
    referenced_transaction_ids: frozenset[int]
    applications: tuple[FusionApplication, ...] = ()

    @property
    def receipt_id(self) -> int:
        return self.receipt.receipt_id


@dataclass(frozen=True, slots=True)
class StudyCase:
    """One remittance (real, or reconstructed from the truth receipt) and its right answer."""

    case_id: int
    truth_receipt_id: int
    currency: str
    amount: Decimal
    payment_date: date
    anchor_account: str | None = None
    invoice_numbers: frozenset[str] = frozenset()  # normalised
    invoice_ids: frozenset[int] = frozenset()
    reference_tokens: frozenset[str] = frozenset()  # normalised remittance references
    payer_name_tokens: frozenset[str] = frozenset()
    bank_account_hashes: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class SkippedSignal:
    signal: SignalName
    reason: str


@dataclass(frozen=True, slots=True)
class SignalStat:
    signal: SignalName
    present: int
    cases: int
    presence_rate: float | None
    precision: float | None
    ambiguous_rate: float | None
    miss_rate: float | None
    circular: bool
    skipped_reason: str | None


@dataclass(frozen=True, slots=True)
class StudyResult:
    pod: str
    date_from: date
    date_to: date
    case_source: CaseSource
    receipts: int
    pool: int
    cases: int
    date_window_days: int
    stats: tuple[SignalStat, ...]
    date_distance: Mapping[Literal["receipt_date", "creation_date"], Mapping[str, int]]
    provisional: bool
    tolerances: Mapping[str, Decimal] = field(default_factory=lambda: {})
