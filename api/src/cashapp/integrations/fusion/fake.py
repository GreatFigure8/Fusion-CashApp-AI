"""`FakeFusionClient`: an in-memory Fusion ledger that behaves like Fusion where it matters.

It enforces overapply, already-applied and GL-date faults and updates balances on apply and
unapply. It is a model of the contract in CONTRACTS.md, never proof of it: the `-m live` probes
confirm the contract against a real non-production pod.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from xml.sax.saxutils import escape

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import to_money
from cashapp.integrations.fusion import bip, query, soap
from cashapp.integrations.fusion.client import ReceiptDateBasis
from cashapp.integrations.fusion.errors import FusionError, FusionFault, fault_from_messages
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    AttachmentRef,
    CustomerRelationship,
    DiscountTier,
    FusionApplication,
    FusionCustomer,
    FusionCustomerSite,
    FusionMessage,
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
    RelationshipDirection,
    TransactionKind,
    UnapplyRequest,
    UnapplyResult,
)

_BOTH: frozenset[RelationshipDirection] = frozenset({"INBOUND", "OUTBOUND"})
_FIRST_TRX_ID = 100001
_FIRST_RECEIPT_ID = 500001
_FIRST_APPLICATION_ID = 900001
_LITERAL = re.compile(r"'((?:[^']|'')*)'")
_Q_EXPR = re.compile(r"^\s*(\w+)\s*(=|in)\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FakeCall:
    method: str
    args: tuple[Any, ...]
    kwargs: Mapping[str, Any]


def _fault(code: str, text: str) -> FusionFault:
    fault = fault_from_messages([FusionMessage(code=code, severity="ERROR", text=text)])
    assert fault is not None  # noqa: S101 - a non-noise code always yields a fault
    return fault


class FakeFusionClient:
    pod_name: str = "fake"

    def __init__(
        self,
        *,
        transactions: Iterable[FusionTransaction] = (),
        receipts: Iterable[FusionReceipt] = (),
        applications: Iterable[FusionApplication] = (),
        customers: Iterable[FusionCustomer] = (),
        payment_terms: Iterable[PaymentTerms] = (),
        relationships: Iterable[CustomerRelationship] = (),
        reports: Mapping[str, bytes] | None = None,
        raw: Mapping[str, bytes] | None = None,
        guard: WriteGuard | None = None,
        relationships_report_path: str = "/Custom/CashApp/Relationships.xdo",
        today: Callable[[], date] | None = None,
    ) -> None:
        self._transactions: dict[int, FusionTransaction] = {
            t.customer_trx_id: t for t in transactions
        }
        self._receipts: dict[int, FusionReceipt] = {r.receipt_id: r for r in receipts}
        self._applications: list[FusionApplication] = list(applications)
        self._customers: dict[str, FusionCustomer] = {c.account_number: c for c in customers}
        self._relationships: list[CustomerRelationship] = list(relationships)
        self._payment_terms: list[PaymentTerms] = list(payment_terms)
        self._reports: dict[str, bytes] = dict(reports or {})
        self._raw: dict[str, bytes] = {**_default_raw(), **(raw or {})}
        self._guard = guard or WriteGuard.allow_all()
        self._relationships_report_path = relationships_report_path
        self._today = today or date.today
        self._comments: dict[int, str] = {
            r.receipt_id: r.comments for r in self._receipts.values() if r.comments is not None
        }
        self._transaction_comments: dict[int, str] = {}
        self._attachments: dict[int, list[AttachmentRef]] = {}
        self._posted: dict[str, list[dict[str, Any]]] = {}
        self._failures: dict[str, list[FusionError | FusionFault]] = {}
        self._next_trx = max([_FIRST_TRX_ID - 1, *self._transactions]) + 1
        self._next_receipt = max([_FIRST_RECEIPT_ID - 1, *self._receipts]) + 1
        self._next_application = (
            max([_FIRST_APPLICATION_ID - 1, *(a.application_id for a in self._applications)]) + 1
        )
        self.calls: list[FakeCall] = []

    # --- construction / serialisation --------------------------------------------------------

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | str | Path, **kwargs: Any) -> FakeFusionClient:
        if isinstance(data, Path):
            data = json.loads(data.read_text(encoding="utf-8"))
        elif isinstance(data, str):
            data = json.loads(data)
        doc = cast("Mapping[str, Any]", data)
        return cls(
            transactions=[_txn_from_json(x) for x in doc.get("transactions", [])],
            receipts=[_receipt_from_json(x) for x in doc.get("receipts", [])],
            applications=[_application_from_json(x) for x in doc.get("applications", [])],
            customers=[_customer_from_json(x) for x in doc.get("customers", [])],
            payment_terms=[_terms_from_json(x) for x in doc.get("payment_terms", [])],
            relationships=[_relationship_from_json(x) for x in doc.get("relationships", [])],
            reports={k: str(v).encode("utf-8") for k, v in doc.get("reports", {}).items()},
            **kwargs,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "customers": [
                {
                    "account_number": c.account_number,
                    "name": c.name,
                    "currency_codes": list(c.currency_codes),
                    "sites": [
                        {
                            "site_number": s.site_number,
                            "purpose": s.purpose,
                            "location": s.location,
                            "address": s.address,
                        }
                        for s in c.sites
                    ],
                }
                for c in self._customers.values()
            ],
            "transactions": [
                {
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
                    "transaction_date": (
                        t.transaction_date.isoformat() if t.transaction_date else None
                    ),
                }
                for t in self._transactions.values()
            ],
            "receipts": [
                {
                    "receipt_id": r.receipt_id,
                    "receipt_number": r.receipt_number,
                    "amount": f"{r.amount:.2f}",
                    "unapplied_amount": f"{r.unapplied_amount:.2f}",
                    "currency": r.currency,
                    "customer_account_number": r.customer_account_number,
                    "receipt_date": r.receipt_date.isoformat(),
                    "creation_date": r.creation_date.isoformat(),
                    "status": r.status,
                    "state": r.state,
                    "remittance_references": list(r.remittance_references),
                    "comments": r.comments,
                }
                for r in self._receipts.values()
            ],
            "applications": [
                {
                    "application_id": a.application_id,
                    "receipt_id": a.receipt_id,
                    "customer_trx_id": a.customer_trx_id,
                    "amount_applied": f"{a.amount_applied:.2f}",
                    "apply_date": a.apply_date.isoformat(),
                    "status": a.status,
                    "discount_amount": (
                        None if a.discount_amount is None else f"{a.discount_amount:.2f}"
                    ),
                }
                for a in self._applications
            ],
            "payment_terms": [
                {
                    "term_id": p.term_id,
                    "name": p.name,
                    "tiers": [
                        {"days": t.days, "percent": f"{t.percent:.2f}"} for t in p.discount_tiers
                    ],
                }
                for p in self._payment_terms
            ],
            "relationships": [
                {
                    "account_number": r.account_number,
                    "related_account_number": r.related_account_number,
                    "related_account_name": r.related_account_name,
                    "directions": sorted(r.directions),
                }
                for r in self._relationships
            ],
            "reports": {k: v.decode("utf-8") for k, v in self._reports.items()},
        }

    # --- fault injection -----------------------------------------------------------------------

    def fail_next(self, method: str, error: FusionError | FusionFault, *, times: int = 1) -> None:
        """Queue a failure. A `FusionError` is raised; a `FusionFault` is returned in the result."""
        self._failures.setdefault(method, []).extend([error] * times)

    def _record(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(FakeCall(method, args, kwargs))

    def _injected(self, method: str) -> FusionError | FusionFault | None:
        queue = self._failures.get(method)
        return queue.pop(0) if queue else None

    def _raise_if_injected(self, method: str) -> None:
        injected = self._injected(method)
        if isinstance(injected, FusionError):
            raise injected
        if isinstance(injected, FusionFault):
            raise FusionError.from_fault(injected)

    # --- ledger read-back ------------------------------------------------------------------------

    def transaction(self, number: str, kind: TransactionKind | None = None) -> FusionTransaction:
        for txn in self._transactions.values():
            if txn.number == number and (kind is None or txn.kind is kind):
                return txn
        raise KeyError(f"no transaction {number}")

    def receipt(self, receipt_id: int) -> FusionReceipt:
        return self._receipts[receipt_id]

    def applications(
        self, *, receipt_id: int | None = None, customer_trx_id: int | None = None
    ) -> list[FusionApplication]:
        return [
            a
            for a in self._applications
            if (receipt_id is None or a.receipt_id == receipt_id)
            and (customer_trx_id is None or a.customer_trx_id == customer_trx_id)
        ]

    def comments(self, receipt_id: int) -> str | None:
        return self._comments.get(receipt_id)

    def attachments(self, receipt_id: int) -> list[AttachmentRef]:
        return list(self._attachments.get(receipt_id, []))

    def posted(self, path: str) -> list[dict[str, Any]]:
        return list(self._posted.get(path, []))

    # --- reads ---------------------------------------------------------------------------------

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]:
        self._record("find_transactions", numbers)
        self._raise_if_injected("find_transactions")
        wanted = set(numbers)
        return [t for t in self._transactions.values() if t.number in wanted]

    async def find_receipts(
        self,
        *,
        customer_numbers: Sequence[str],
        date_from: date,
        date_to: date,
        by: ReceiptDateBasis = "receipt_date",
    ) -> list[FusionReceipt]:
        self._record(
            "find_receipts",
            customer_numbers=customer_numbers,
            date_from=date_from,
            date_to=date_to,
            by=by,
        )
        self._raise_if_injected("find_receipts")
        customers = set(customer_numbers)
        found: list[FusionReceipt] = []
        for receipt in self._receipts.values():
            when = receipt.receipt_date if by == "receipt_date" else receipt.creation_date.date()
            if receipt.customer_account_number in customers and date_from <= when <= date_to:
                found.append(receipt)
        return found

    async def receipts_created_since(
        self, since: datetime, *, limit: int = 500
    ) -> list[FusionReceipt]:
        self._record("receipts_created_since", since, limit=limit)
        self._raise_if_injected("receipts_created_since")
        ordered = sorted(
            (r for r in self._receipts.values() if r.creation_date >= since),
            key=lambda r: (r.creation_date, r.receipt_id),
        )
        return ordered[:limit]

    async def get_receipt(self, receipt_id: int) -> FusionReceipt:
        self._record("get_receipt", receipt_id)
        self._raise_if_injected("get_receipt")
        try:
            return self._receipts[receipt_id]
        except KeyError:
            raise FusionError(
                ErrorCode.FUSION_FAULT, "receipt not found", http_status=404, retryable=False
            ) from None

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]:
        self._record("list_receipt_applications", receipt_id)
        self._raise_if_injected("list_receipt_applications")
        return self.applications(receipt_id=receipt_id)

    async def list_transaction_applications(self, customer_trx_id: int) -> list[FusionApplication]:
        self._record("list_transaction_applications", customer_trx_id)
        self._raise_if_injected("list_transaction_applications")
        return self.applications(customer_trx_id=customer_trx_id)

    async def list_receipt_attachments(self, receipt_id: int) -> list[AttachmentRef]:
        self._record("list_receipt_attachments", receipt_id)
        self._raise_if_injected("list_receipt_attachments")
        return self.attachments(receipt_id)

    async def get_customer_account(self, account_number: str) -> FusionCustomer:
        self._record("get_customer_account", account_number)
        self._raise_if_injected("get_customer_account")
        try:
            return self._customers[account_number]
        except KeyError:
            raise FusionError(
                ErrorCode.CUSTOMER_NOT_FOUND, "customer account not found", retryable=False
            ) from None

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None:
        self._record("get_payment_terms", term)
        self._raise_if_injected("get_payment_terms")
        for terms in self._payment_terms:
            if (isinstance(term, int) and terms.term_id == term) or terms.name == term:
                return terms
        return None

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]:
        self._record("customer_relationships", account_numbers)
        self._raise_if_injected("customer_relationships")
        return bip.parse_relationships_xml(self._render_relationships(account_numbers))

    def _render_relationships(self, account_numbers: Sequence[str]) -> bytes:
        wanted = set(account_numbers)
        rows: list[str] = []
        for rel in self._relationships:
            if rel.account_number not in wanted:
                continue
            for direction in sorted(rel.directions):
                rows.append(
                    "<G_1>"
                    f"<ACCOUNT_NUMBER>{escape(rel.account_number)}</ACCOUNT_NUMBER>"
                    f"<RELATED_ACCOUNT_NUMBER>{escape(rel.related_account_number)}"
                    "</RELATED_ACCOUNT_NUMBER>"
                    f"<RELATED_ACCOUNT_NAME>{escape(rel.related_account_name or '')}"
                    "</RELATED_ACCOUNT_NAME>"
                    f"<DIRECTION>{direction}</DIRECTION></G_1>"
                )
        return f"<DATA_DS>{''.join(rows)}</DATA_DS>".encode()

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes:
        self._record("run_report", path, params, fmt=fmt)
        self._raise_if_injected("run_report")
        if path == self._relationships_report_path:
            accounts = [a for a in params.get(bip.RELATIONSHIPS_PARAM, "").split(",") if a]
            return self._render_relationships(accounts)
        try:
            return self._reports[path]
        except KeyError:
            raise FusionError(
                ErrorCode.FUSION_FAULT, f"report not found: {path}", retryable=False
            ) from None

    async def rest_get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        self._record("rest_get", path, params)
        self._raise_if_injected("rest_get")
        resource = _resource(path)
        params = params or {}
        rows: list[dict[str, Any]]
        key: str
        if resource == "standardReceipts/describe":
            return json.loads(_RECEIPT_DESCRIBE)
        if resource == _resource(query.CUSTOMER_ACCOUNTS_PATH):
            key = "AccountNumber"
            rows = [_customer_account_row(c) for c in self._customers.values()]
        elif resource == "receivablesInvoices":
            key = "TransactionNumber"
            rows = [
                _invoice_row(t)
                for t in self._transactions.values()
                if t.kind is TransactionKind.INVOICE
            ]
        elif resource == "receivablesCreditMemos":
            key = "TransactionNumber"
            rows = [
                _credit_memo_row(t)
                for t in self._transactions.values()
                if t.kind is TransactionKind.CREDIT_MEMO
            ]
        elif resource == "standardReceipts":
            key = "ReceiptNumber"
            rows = [_receipt_row(r) for r in self._receipts.values()]
        else:
            raise FusionError(
                ErrorCode.FUSION_FAULT, f"unsupported resource {resource}", http_status=404
            )
        for row in rows:
            if resource != "standardReceipts":
                row["Comments"] = self._transaction_comments.get(row["CustomerTransactionId"])
        wanted = _q_values(params.get("q"), key)
        if wanted is not None:
            rows = [row for row in rows if row.get(key) in wanted]
        offset = int(params.get("offset", "0"))
        limit = int(params.get("limit", str(len(rows) or 1)))
        page = rows[offset : offset + limit]
        return {
            "items": page,
            "hasMore": offset + len(page) < len(rows),
            "count": len(page),
            "limit": limit,
            "offset": offset,
        }

    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes:
        self._record("get_raw", path, params)
        self._raise_if_injected("get_raw")
        key = path.split("?", 1)[0]
        try:
            return self._raw[key]
        except KeyError:
            raise FusionError(
                ErrorCode.FUSION_FAULT, f"not found: {key}", http_status=404, retryable=False
            ) from None

    # --- writes --------------------------------------------------------------------------------

    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult:
        self._guard.check("apply_receipt")
        self._record("apply_receipt", request)
        injected = self._injected("apply_receipt")
        if isinstance(injected, FusionError):
            raise injected
        if isinstance(injected, FusionFault):
            return self._failed_apply(request, injected)
        fault = self._apply_fault(request)
        if fault is not None:
            return self._failed_apply(request, fault)
        txn = self._transactions[request.customer_trx_id]
        receipt = self._receipts[request.receipt_id]
        application_id = self._next_application
        self._next_application += 1
        self._applications.append(
            FusionApplication(
                application_id=application_id,
                receipt_id=request.receipt_id,
                customer_trx_id=request.customer_trx_id,
                amount_applied=request.amount_applied,
                apply_date=request.application_date,
                status="APP",
                discount_amount=request.discount_amount,
            )
        )
        self._transactions[txn.customer_trx_id] = replace(
            txn,
            balance=to_money(
                txn.balance - request.amount_applied - (request.discount_amount or Decimal(0))
            ),
        )
        self._receipts[receipt.receipt_id] = replace(
            receipt, unapplied_amount=to_money(receipt.unapplied_amount - request.amount_applied)
        )
        return ApplyResult(
            ok=True,
            application_id=application_id,
            fault=None,
            raw_messages=(),
            receipt_id=request.receipt_id,
        )

    @staticmethod
    def _failed_apply(request: ApplyRequest, fault: FusionFault) -> ApplyResult:
        return ApplyResult(
            ok=False,
            application_id=None,
            fault=fault,
            raw_messages=fault.messages,
            receipt_id=request.receipt_id,
        )

    def _apply_fault(self, request: ApplyRequest) -> FusionFault | None:
        receipt = self._receipts.get(request.receipt_id)
        txn = self._transactions.get(request.customer_trx_id)
        if receipt is None or txn is None:
            return _fault("FAKE_NOT_FOUND", "receipt or transaction not found")
        if request.receipt_currency != receipt.currency or txn.currency != receipt.currency:
            return _fault("FAKE_CURRENCY", "currency mismatch between receipt and transaction")
        if any(
            a.status == "APP"
            and a.receipt_id == request.receipt_id
            and a.customer_trx_id == request.customer_trx_id
            for a in self._applications
        ):
            return _fault("AR-856102", "receipt is already applied to this transaction")
        amount = request.amount_applied
        discount = request.discount_amount
        if discount is not None:
            rejected = self._discount_fault(request, txn)
            if rejected is not None:
                return rejected
            if amount + discount > txn.balance:
                return _fault("AR-855287", "application exceeds the available balance")
        over_balance = amount > txn.balance if amount >= 0 else amount < txn.balance
        if over_balance or (amount > 0 and amount > receipt.unapplied_amount):
            return _fault("AR-855287", "application exceeds the available balance")
        if request.accounting_date < receipt.receipt_date:
            return _fault("AR-856089", "accounting date is before the receipt GL date")
        return None

    def _discount_fault(self, request: ApplyRequest, txn: FusionTransaction) -> FusionFault | None:
        """Model Fusion's rule: a discount needs an invoice on terms still within a tier."""
        discount = request.discount_amount or Decimal("0.00")
        reason: str | None = None
        terms = next((p for p in self._payment_terms if p.name == txn.payment_terms), None)
        if txn.kind is not TransactionKind.INVOICE or discount <= 0:
            reason = "a discount cannot be taken on this application"
        elif terms is None or txn.transaction_date is None:
            reason = "the transaction has no payment terms or invoice date"
        else:
            elapsed = (request.application_date - txn.transaction_date).days
            earned = [t for t in terms.discount_tiers if 0 <= elapsed <= t.days]
            if not earned:
                reason = "the payment is outside every discount tier"
            else:
                best = max(t.percent for t in earned)
                if discount > to_money(txn.balance * best / 100) + Decimal("0.005"):
                    reason = "the discount exceeds the earned discount"
        if reason is None:
            return None
        message = FusionMessage(code=None, severity="ERROR", text=reason)
        return FusionFault(
            code=ErrorCode.FUSION_DISCOUNT_REJECTED,
            fusion_code=None,
            message=reason,
            messages=(message,),
        )

    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult:
        self._guard.check("unapply_receipt")
        self._record("unapply_receipt", request)
        injected = self._injected("unapply_receipt")
        if isinstance(injected, FusionError):
            raise injected
        if isinstance(injected, FusionFault):
            return UnapplyResult(ok=False, fault=injected, raw_messages=injected.messages)
        for index, app in enumerate(self._applications):
            if (
                app.application_id == request.application_id
                and app.receipt_id == request.receipt_id
                and app.status == "APP"
            ):
                txn = self._transactions[app.customer_trx_id]
                receipt = self._receipts[app.receipt_id]
                self._transactions[txn.customer_trx_id] = replace(
                    txn,
                    balance=to_money(
                        txn.balance + app.amount_applied + (app.discount_amount or Decimal(0))
                    ),
                )
                self._receipts[receipt.receipt_id] = replace(
                    receipt,
                    unapplied_amount=to_money(receipt.unapplied_amount + app.amount_applied),
                )
                self._applications[index] = replace(app, status="REVERSED")
                return UnapplyResult(ok=True, fault=None, raw_messages=())
        fault = _fault("FAKE_NOT_FOUND", "no active application to reverse")
        return UnapplyResult(ok=False, fault=fault, raw_messages=fault.messages)

    async def set_receipt_comment(self, receipt_id: int, text: str) -> None:
        self._guard.check("set_receipt_comment")
        self._record("set_receipt_comment", receipt_id, text)
        self._raise_if_injected("set_receipt_comment")
        receipt = await self._known_receipt(receipt_id)
        self._comments[receipt_id] = text
        self._receipts[receipt_id] = replace(receipt, comments=text)

    async def attach_to_receipt(
        self, receipt_id: int, filename: str, content: bytes, content_type: str, title: str
    ) -> AttachmentRef:
        self._guard.check("attach_to_receipt")
        self._record("attach_to_receipt", receipt_id, filename, content, content_type, title)
        self._raise_if_injected("attach_to_receipt")
        await self._known_receipt(receipt_id)
        existing = self._attachments.setdefault(receipt_id, [])
        ref = AttachmentRef(receipt_id, f"ATT-{receipt_id}-{len(existing) + 1}", filename, title)
        existing.append(ref)
        return ref

    async def _known_receipt(self, receipt_id: int) -> FusionReceipt:
        receipt = self._receipts.get(receipt_id)
        if receipt is None:
            raise FusionError(
                ErrorCode.FUSION_FAULT, "receipt not found", http_status=404, retryable=False
            )
        return receipt

    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]:
        self._guard.check("rest_post")
        self._record("rest_post", path, json)
        self._raise_if_injected("rest_post")
        resource = _resource(path)
        body = dict(json)
        self._posted.setdefault(resource, []).append(body)
        if resource == "receivablesInvoices":
            return self._create_transaction(body, TransactionKind.INVOICE)
        if resource == "receivablesCreditMemos":
            return self._create_transaction(body, TransactionKind.CREDIT_MEMO)
        if resource == "standardReceipts":
            return self._create_receipt(body)
        match = re.fullmatch(
            r"receivables(?:Invoices|CreditMemos)/(\d+)/action/completeTransaction", resource
        )
        if match is not None:
            trx_id = int(match.group(1))
            txn = self._transactions.get(trx_id)
            if txn is None:
                raise FusionError(
                    ErrorCode.FUSION_FAULT,
                    "transaction not found",
                    http_status=404,
                    retryable=False,
                )
            self._transactions[trx_id] = replace(txn, status="Open")
            return {"result": "OK"}
        raise FusionError(
            ErrorCode.FUSION_FAULT,
            f"unsupported POST path {resource}",
            http_status=404,
            retryable=False,
        )

    def _create_transaction(self, body: Mapping[str, Any], kind: TransactionKind) -> dict[str, Any]:
        trx_id = self._next_trx
        self._next_trx += 1
        number = str(body.get("TransactionNumber") or f"FAKE-{trx_id}")
        amount = _body_amount(body)
        signed = -abs(amount) if kind is TransactionKind.CREDIT_MEMO else amount
        currency = str(body.get("InvoiceCurrencyCode") or body.get("CurrencyCode") or "USD")
        status = "Incomplete" if kind is TransactionKind.INVOICE else "Open"
        self._transactions[trx_id] = FusionTransaction(
            customer_trx_id=trx_id,
            number=number,
            kind=kind,
            balance=signed,
            original_amount=signed,
            currency=currency,
            status=status,
            bill_to_customer_number=_opt(body.get("BillToCustomerNumber")),
            bill_to_site=_opt(body.get("BillToSite")),
            business_unit=_opt(body.get("BusinessUnit")),
            payment_terms=_opt(body.get("PaymentTerms")),
        )
        comments = _opt(body.get("Comments"))
        if comments is not None:
            self._transaction_comments[trx_id] = comments
        return {"CustomerTransactionId": trx_id, "TransactionNumber": number}

    def _create_receipt(self, body: Mapping[str, Any]) -> dict[str, Any]:
        receipt_id = self._next_receipt
        self._next_receipt += 1
        amount = to_money(str(body.get("Amount", "0")))
        receipt_date = date.fromisoformat(str(body.get("ReceiptDate") or self._today())[:10])
        comments = _opt(body.get("Comments"))
        references = tuple(
            str(ref[query.FIELDS_REMITTANCE_REFERENCE])
            for ref in cast("list[Mapping[str, Any]]", body.get("remittanceReferences") or [])
            if ref.get(query.FIELDS_REMITTANCE_REFERENCE) is not None
        )
        receipt = FusionReceipt(
            receipt_id=receipt_id,
            receipt_number=str(body.get("ReceiptNumber") or f"FAKE-R-{receipt_id}"),
            amount=amount,
            unapplied_amount=amount,
            currency=str(body.get("Currency") or "USD"),
            customer_account_number=_opt(body.get("CustomerAccountNumber")),
            receipt_date=receipt_date,
            creation_date=datetime.combine(self._today(), datetime.min.time(), tzinfo=UTC),
            status="UNAPP",
            state="CLEARED",
            remittance_references=references,
            comments=comments,
        )
        self._receipts[receipt_id] = receipt
        if comments is not None:
            self._comments[receipt_id] = comments
        return {"StandardReceiptId": receipt_id, "ReceiptNumber": receipt.receipt_number}

    async def aclose(self) -> None:
        self._record("aclose")


# --- helpers ------------------------------------------------------------------------------------


def _opt(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


_WSDL_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" name="{name}">'
    '<wsdl:portType name="{name}"><wsdl:operation name="{operation}"/></wsdl:portType>'
    "</wsdl:definitions>"
)

_RECEIPT_DESCRIBE = json.dumps(
    {
        "Resources": {
            "standardReceipts": {"children": {"attachments": {}, "remittanceReferences": {}}}
        }
    }
)


def _default_raw() -> dict[str, bytes]:
    """Minimal WSDL shapes for the two SOAP services and the receipt describe (UNVERIFIED)."""
    return {
        soap.SOAP_PATH_RECEIPTS: _WSDL_TEMPLATE.format(
            name="StandardReceiptService", operation="createApplyReceipt"
        ).encode(),
        bip.BIP_PATH: _WSDL_TEMPLATE.format(
            name="ExternalReportWSSService", operation="runReport"
        ).encode(),
    }


def _customer_account_row(c: FusionCustomer) -> dict[str, Any]:
    return {"AccountNumber": c.account_number, "PartyName": c.name}


def _resource(path: str) -> str:
    stripped = path[len(query.REST_BASE) :] if path.startswith(query.REST_BASE) else path
    return stripped.strip("/")


def _q_values(q: str | None, key: str) -> set[str] | None:
    if not q:
        return None
    match = _Q_EXPR.match(q)
    if match is None or match.group(1) != key:
        return None
    return {m.replace("''", "'") for m in _LITERAL.findall(match.group(3))}


def _body_amount(body: Mapping[str, Any]) -> Decimal:
    if body.get("EnteredAmount") is not None:
        return abs(to_money(str(body["EnteredAmount"])))
    total = Decimal("0.00")
    lines = cast("list[Mapping[str, Any]]", body.get("receivablesInvoiceLines") or [])
    for line in lines:
        total += Decimal(str(line.get("Quantity", 1))) * Decimal(
            str(line.get("UnitSellingPrice", 0))
        )
    return to_money(total)


def _invoice_row(t: FusionTransaction) -> dict[str, Any]:
    return {
        "CustomerTransactionId": t.customer_trx_id,
        "TransactionNumber": t.number,
        "InvoiceBalanceAmount": t.balance,
        "EnteredAmount": t.original_amount,
        "BillToCustomerNumber": t.bill_to_customer_number,
        "BillToSite": t.bill_to_site,
        "BusinessUnit": t.business_unit,
        "InvoiceCurrencyCode": t.currency,
        "InvoiceStatus": t.status,
        "PaymentTerms": t.payment_terms,
        "TransactionDate": t.transaction_date.isoformat() if t.transaction_date else None,
    }


def _credit_memo_row(t: FusionTransaction) -> dict[str, Any]:
    return {
        "CustomerTransactionId": t.customer_trx_id,
        "TransactionNumber": t.number,
        "TransactionBalanceDue": t.balance,
        "EnteredAmount": t.original_amount,
        "BillToCustomerNumber": t.bill_to_customer_number,
        "BillToSite": t.bill_to_site,
        "BusinessUnit": t.business_unit,
        "CurrencyCode": t.currency,
        "TransactionStatus": t.status,
    }


def _receipt_row(r: FusionReceipt) -> dict[str, Any]:
    return {
        "StandardReceiptId": r.receipt_id,
        "ReceiptNumber": r.receipt_number,
        "Amount": r.amount,
        "UnappliedAmount": r.unapplied_amount,
        "Currency": r.currency,
        "CustomerAccountNumber": r.customer_account_number,
        "ReceiptDate": r.receipt_date.isoformat(),
        "CreationDate": r.creation_date.isoformat(),
        "Status": r.status,
        "State": r.state,
        "Comments": r.comments,
        "remittanceReferences": [{"ReferenceNumber": ref} for ref in r.remittance_references],
    }


def _txn_from_json(x: Mapping[str, Any]) -> FusionTransaction:
    return FusionTransaction(
        customer_trx_id=int(x["customer_trx_id"]),
        number=str(x["number"]),
        kind=TransactionKind(x["kind"]),
        balance=to_money(str(x["balance"])),
        original_amount=to_money(str(x["original_amount"])),
        currency=str(x["currency"]),
        status=str(x["status"]),
        bill_to_customer_number=_opt(x.get("bill_to_customer_number")),
        bill_to_site=_opt(x.get("bill_to_site")),
        business_unit=_opt(x.get("business_unit")),
        payment_terms=_opt(x.get("payment_terms")),
        transaction_date=(
            date.fromisoformat(str(x["transaction_date"])) if x.get("transaction_date") else None
        ),
    )


def _receipt_from_json(x: Mapping[str, Any]) -> FusionReceipt:
    return FusionReceipt(
        receipt_id=int(x["receipt_id"]),
        receipt_number=str(x["receipt_number"]),
        amount=to_money(str(x["amount"])),
        unapplied_amount=to_money(str(x["unapplied_amount"])),
        currency=str(x["currency"]),
        customer_account_number=_opt(x.get("customer_account_number")),
        receipt_date=date.fromisoformat(str(x["receipt_date"])),
        creation_date=datetime.fromisoformat(str(x["creation_date"])),
        status=str(x["status"]),
        state=str(x["state"]),
        remittance_references=tuple(str(r) for r in x.get("remittance_references", [])),
        comments=_opt(x.get("comments")),
    )


def _application_from_json(x: Mapping[str, Any]) -> FusionApplication:
    return FusionApplication(
        application_id=int(x["application_id"]),
        receipt_id=int(x["receipt_id"]),
        customer_trx_id=int(x["customer_trx_id"]),
        amount_applied=to_money(str(x["amount_applied"])),
        apply_date=date.fromisoformat(str(x["apply_date"])),
        status=str(x["status"]),
        discount_amount=(
            to_money(str(x["discount_amount"])) if x.get("discount_amount") is not None else None
        ),
    )


def _terms_from_json(x: Mapping[str, Any]) -> PaymentTerms:
    tiers = sorted(
        (
            DiscountTier(days=int(t["days"]), percent=Decimal(str(t["percent"])))
            for t in x.get("tiers", [])
        ),
        key=lambda t: t.days,
    )
    return PaymentTerms(
        term_id=int(x["term_id"]) if x.get("term_id") is not None else None,
        name=str(x["name"]),
        discount_tiers=tuple(tiers),
    )


def _customer_from_json(x: Mapping[str, Any]) -> FusionCustomer:
    return FusionCustomer(
        account_number=str(x["account_number"]),
        name=str(x["name"]),
        currency_codes=tuple(str(c) for c in x.get("currency_codes", [])),
        sites=tuple(
            FusionCustomerSite(
                site_number=str(s["site_number"]),
                purpose=_opt(s.get("purpose")),
                location=_opt(s.get("location")),
                address=_opt(s.get("address")),
            )
            for s in x.get("sites", [])
        ),
    )


def _relationship_from_json(x: Mapping[str, Any]) -> CustomerRelationship:
    raw = x.get("directions")
    directions = _BOTH if raw is None else frozenset(cast("list[RelationshipDirection]", raw))
    return CustomerRelationship(
        account_number=str(x["account_number"]),
        related_account_number=str(x["related_account_number"]),
        related_account_name=_opt(x.get("related_account_name")),
        directions=directions,
    )
