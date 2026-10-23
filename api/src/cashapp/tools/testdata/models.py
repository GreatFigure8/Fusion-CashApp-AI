"""Serialised shapes of the test-data generator: plans, expectations, manifests, reports."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.money import CurrencyCode, MoneyStr
from cashapp.domain.status import LineStatus


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ScenarioName(StrEnum):
    ONE_TO_ONE = "one_to_one"
    SPLIT_PAYMENT = "split_payment"
    SHORT_PAY = "short_pay"
    INR_ROUNDING = "inr_rounding"
    DUPLICATE_AMOUNTS = "duplicate_amounts"
    AMBIGUOUS_RECEIPTS = "ambiguous_receipts"
    CREDIT_MEMO_NETTING = "credit_memo_netting"
    ALREADY_APPLIED = "already_applied"


class ScenarioParams(_Frozen):
    currency: CurrencyCode = "USD"
    lines: int = Field(3, ge=1, le=50)
    seed: int = 0
    as_of: date  # the payment date


class PlannedTransaction(_Frozen):
    number: str
    amount: MoneyStr  # credit memos negative
    currency: CurrencyCode
    terms: str | None = None
    transaction_date: date


class PlannedReceipt(_Frozen):
    number: str
    amount: MoneyStr
    currency: CurrencyCode
    receipt_date: date
    references: list[str] = Field(default_factory=list[str])


class PlannedApplication(_Frozen):
    receipt_number: str
    transaction_number: str
    amount: MoneyStr  # signed


class ExpectedLine(_Frozen):
    number: str
    line_status: LineStatus
    applied_amount: MoneyStr


class Expected(_Frozen):
    receipt_number: str | None
    lines: list[ExpectedLine]
    error_code: ErrorCode | None = None
    residual: MoneyStr = Decimal("0.00")


class ScenarioPlan(_Frozen):
    scenario: ScenarioName
    tag: str
    params: ScenarioParams
    customer_account: str
    invoices: list[PlannedTransaction]
    credit_memos: list[PlannedTransaction]
    receipts: list[PlannedReceipt]
    pre_applications: list[PlannedApplication] = Field(default_factory=list[PlannedApplication])
    remittance: RemittanceExtraction
    expected: Expected


class CreatedRecord(_Frozen):
    kind: Literal["INVOICE", "CREDIT_MEMO", "RECEIPT", "APPLICATION"]
    number: str
    fusion_id: int | None = None


class GeneratedData(_Frozen):
    tag: str
    scenario: ScenarioName
    pod_name: str
    created_at: datetime
    records: list[CreatedRecord]

    def ids_by_number(self) -> dict[str, int]:
        """Fusion ids of the created invoices, credit memos and receipts, keyed by number."""
        return {
            r.number: r.fusion_id
            for r in self.records
            if r.kind != "APPLICATION" and r.fusion_id is not None
        }


class TaggedRecord(_Frozen):
    kind: Literal["INVOICE", "CREDIT_MEMO", "RECEIPT"]
    number: str
    fusion_id: int | None = None
    status: str | None = None
    found: bool


class CleanupReport(_Frozen):
    tag: str
    pod_name: str
    records: list[TaggedRecord]
