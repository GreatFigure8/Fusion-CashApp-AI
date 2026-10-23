"""The customer-resolution result: who the payer is in Fusion, and what Fusion knows of the lines.

Pure value types plus the JSON round trip for the transactions stored with the result. Nothing
here does IO, so the repository (data layer) and the service (business layer) share it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from cashapp.domain.money import to_money
from cashapp.domain.status import InfoFlag, LineStatus
from cashapp.integrations.fusion.models import FusionTransaction, TransactionKind


class ResolutionMethod(StrEnum):
    ALIAS = "alias"
    INVOICE = "invoice"
    HUMAN = "human"


class LineFindingStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    NO_BILL_TO = "NO_BILL_TO"
    CUSTOMER_MISMATCH = "CUSTOMER_MISMATCH"


CurrencySource = Literal["extraction", "customer", "anchor_transactions"]


@dataclass(frozen=True, slots=True)
class LineCustomerFinding:
    line_no: int
    transaction_number: str
    status: LineFindingStatus
    candidate_status: LineStatus | None  # the line's pre-verdict for line matching
    customer_trx_ids: tuple[int, ...]
    bill_to_customer_numbers: tuple[str, ...]  # distinct, non-null, sorted


@dataclass(frozen=True, slots=True)
class CustomerResolution:
    anchor_customer_number: str
    related_customer_numbers: tuple[str, ...]  # sorted, deduplicated, anchor excluded
    method: ResolutionMethod
    alias_ids: tuple[int, ...]
    transactions: list[FusionTransaction]  # everything find_transactions returned
    currency: str | None
    flags: set[InfoFlag]
    anchor_line_no: int | None = None  # None for the alias and human paths
    currency_source: CurrencySource | None = None
    line_findings: tuple[LineCustomerFinding, ...] = ()

    def owners(self) -> tuple[str, ...]:
        """The accounts whose receipts may pay this remittance: the anchor, then related ones."""
        return (self.anchor_customer_number, *self.related_customer_numbers)

    def transactions_for(self, number: str) -> list[FusionTransaction]:
        wanted = number.strip()
        return [t for t in self.transactions if t.number == wanted]


def transaction_to_json(t: FusionTransaction) -> dict[str, Any]:
    """Money as 2 dp strings; the number stays a string."""
    return {
        "customer_trx_id": t.customer_trx_id,
        "number": t.number,
        "kind": t.kind.value,
        "balance": f"{t.balance:.2f}",
        "original_amount": f"{t.original_amount:.2f}",
        "currency": t.currency,
        "status": t.status,
        "bill_to_customer_number": t.bill_to_customer_number,
        "bill_to_site": t.bill_to_site,
        "business_unit": t.business_unit,
        "payment_terms": t.payment_terms,
    }


def transaction_from_json(d: Mapping[str, Any]) -> FusionTransaction:
    return FusionTransaction(
        customer_trx_id=int(d["customer_trx_id"]),
        number=str(d["number"]),
        kind=TransactionKind(d["kind"]),
        balance=to_money(str(d["balance"])),
        original_amount=to_money(str(d["original_amount"])),
        currency=str(d["currency"]),
        status=str(d["status"]),
        bill_to_customer_number=d.get("bill_to_customer_number"),
        bill_to_site=d.get("bill_to_site"),
        business_unit=d.get("business_unit"),
        payment_terms=d.get("payment_terms"),
    )


def finding_to_json(f: LineCustomerFinding) -> dict[str, Any]:
    return {
        "line_no": f.line_no,
        "transaction_number": f.transaction_number,
        "status": f.status.value,
        "candidate_status": f.candidate_status.value if f.candidate_status is not None else None,
        "customer_trx_ids": list(f.customer_trx_ids),
        "bill_to_customer_numbers": list(f.bill_to_customer_numbers),
    }


def finding_from_json(d: Mapping[str, Any]) -> LineCustomerFinding:
    candidate = d.get("candidate_status")
    return LineCustomerFinding(
        line_no=int(d["line_no"]),
        transaction_number=str(d["transaction_number"]),
        status=LineFindingStatus(d["status"]),
        candidate_status=LineStatus(candidate) if candidate is not None else None,
        customer_trx_ids=tuple(int(i) for i in d.get("customer_trx_ids", ())),
        bill_to_customer_numbers=tuple(str(c) for c in d.get("bill_to_customer_numbers", ())),
    )
