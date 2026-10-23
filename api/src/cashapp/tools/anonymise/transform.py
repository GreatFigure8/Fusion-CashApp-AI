"""Source bundle in, anonymised ``PriorFixtures`` out.

Pure and deterministic: the result depends on the bundle's content and the key only, never on file
or row order. Pseudonyms come from ``Pseudonymiser``, amounts from ``AmountMapper`` and the
extraction rows are built through the real ``RemittanceExtraction`` model.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any, Final

from cashapp.domain.extraction import LineKind, RemittanceExtraction
from cashapp.domain.iso4217 import is_iso_4217
from cashapp.domain.money import money_eq
from cashapp.tools.anonymise.amounts import AmountGroup, AmountMapper, ClusterIndex
from cashapp.tools.anonymise.fixture_format import (
    FORMAT_VERSION,
    LineLabel,
    OutcomeLine,
    PriorFailure,
    PriorFixtures,
    PriorManifest,
    PriorMessage,
    PriorOutcome,
)
from cashapp.tools.anonymise.keys import key_id
from cashapp.tools.anonymise.pseudonym import Kind, Pseudonymiser
from cashapp.tools.anonymise.source import (
    APPLICATIONS_FILE,
    SourceAllocation,
    SourceApplication,
    SourceBundle,
    SourceFormatError,
    SourceMessage,
    SourceReceipt,
    SourceTransaction,
)

GENERATED_BY: Final = "cashapp.tools.anonymise"
FIRST_TRANSACTION_ID: Final = 100001
FIRST_RECEIPT_ID: Final = 500001
FIRST_APPLICATION_ID: Final = 900001
_BOTH_DIRECTIONS: Final = ["INBOUND", "OUTBOUND"]
_SOURCE: Final[dict[str, int]] = {"part_no": 1}

_Json = dict[str, Any]


def _fmt(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _present(value: Any, *, source: bool = True) -> _Json:
    return {
        "value": value,
        "source": dict(_SOURCE) if source and value is not None else None,
        "confidence": 1.0 if value is not None else 0.0,
    }


def anonymise(bundle: SourceBundle, key: bytes) -> PriorFixtures:
    return _Transform(bundle, key).run()


class _Transform:
    def __init__(self, bundle: SourceBundle, key: bytes) -> None:
        self._b = bundle
        self._key = key
        self._p = Pseudonymiser(key)
        self._txns: dict[str, SourceTransaction] = {t.number: t for t in bundle.transactions}
        self._receipts: dict[str, SourceReceipt] = {r.receipt_number: r for r in bundle.receipts}
        self._apps_by_txn: dict[str, list[SourceApplication]] = defaultdict(list)
        self._apps_by_receipt: dict[str, list[SourceApplication]] = defaultdict(list)
        for app in bundle.applications:
            if app.transaction_number not in self._txns or app.receipt_number not in self._receipts:
                raise SourceFormatError(
                    APPLICATIONS_FILE, 0, "receipt_number", "application refers to a missing row"
                )
            self._apps_by_txn[app.transaction_number].append(app)
            self._apps_by_receipt[app.receipt_number].append(app)
        self._register()
        self._p.freeze()
        self._index = ClusterIndex()
        self._mapper = AmountMapper(self._index, label=self._label, digest=self._p.digest_int)
        self._currency_by_message = {
            m.message_id: (m.payment_currency or "").upper() for m in bundle.messages
        }

    # --- registration ----------------------------------------------------------------------------

    def _register(self) -> None:
        p, b = self._p, self._b
        for customer in b.customers:
            p.register(Kind.ACCOUNT, customer.account_number)
            p.register(Kind.CUSTOMER_NAME, customer.name)
        for txn in b.transactions:
            p.register(Kind.INVOICE, txn.number)
            p.register(Kind.ACCOUNT, txn.bill_to_customer_number)
            p.register(Kind.SITE, txn.bill_to_site)
            p.register(Kind.BUSINESS_UNIT, txn.business_unit)
            p.register(Kind.TERMS, txn.payment_terms)
        for receipt in b.receipts:
            p.register(Kind.RECEIPT, receipt.receipt_number)
            p.register(Kind.ACCOUNT, receipt.customer_account_number)
            p.register_many(Kind.REFERENCE, receipt.remittance_references)
            p.register(Kind.BANK, receipt.payer_bank_account)
        for app in b.applications:
            p.register(Kind.RECEIPT, app.receipt_number)
            p.register(Kind.INVOICE, app.transaction_number)
        for rel in b.relationships:
            p.register(Kind.ACCOUNT, rel.account_number)
            p.register(Kind.ACCOUNT, rel.related_account_number)
        for msg in b.messages:
            p.register(Kind.MESSAGE, msg.message_id)
            p.register(Kind.CUSTOMER_NAME, msg.payer_name)
            p.register(Kind.BANK, msg.payer_bank_account)
            p.register(Kind.REFERENCE, msg.reference_number)
            p.register_many(Kind.PURCHASE_ORDER, msg.po_refs)
            p.register_many(Kind.SALES_ORDER, msg.sales_order_refs)
            p.register_many(Kind.ERS, msg.ers_refs)
            for alloc in msg.allocations:
                p.register(Kind.INVOICE, alloc.transaction_number)
                p.register(Kind.PURCHASE_ORDER, alloc.po_number)
                p.register(Kind.SALES_ORDER, alloc.sales_order)
                p.register(Kind.ERS, alloc.ers_reference)
            for line in msg.outcome.lines:
                p.register(Kind.INVOICE, line.transaction_number)
            p.register(Kind.RECEIPT, msg.outcome.receipt_number)
        for failure in b.failures:
            p.register(Kind.MESSAGE, failure.message_id)
            for label in failure.lines:
                p.register(Kind.INVOICE, label.transaction_number)

    # --- clusters --------------------------------------------------------------------------------

    @staticmethod
    def _acct(number: str) -> str:
        return f"acct:{number.strip()}"

    def _txn_member(self, number: str) -> str:
        txn = self._txns.get(number)
        if txn is not None and txn.bill_to_customer_number:
            return self._acct(txn.bill_to_customer_number)
        return f"txn:{number}"

    def _receipt_member(self, number: str) -> str:
        receipt = self._receipts.get(number)
        if receipt is not None and receipt.customer_account_number:
            return self._acct(receipt.customer_account_number)
        return f"rcpt:{number}"

    def _label(self, member: str) -> str:
        prefix, _, rest = member.partition(":")
        kinds = {
            "acct": Kind.ACCOUNT,
            "msg": Kind.MESSAGE,
            "txn": Kind.INVOICE,
            "rcpt": Kind.RECEIPT,
        }
        return self._p.map(kinds[prefix], rest)

    def _build_clusters(self) -> None:
        index = self._index
        for rel in self._b.relationships:
            index.union(self._acct(rel.account_number), self._acct(rel.related_account_number))
        for app in self._b.applications:
            index.union(
                self._receipt_member(app.receipt_number), self._txn_member(app.transaction_number)
            )
        for msg in self._b.messages:
            member = f"msg:{msg.message_id}"
            index.add(member)
            numbers = {a.transaction_number for a in msg.allocations}
            numbers.update(line.transaction_number for line in msg.outcome.lines)
            for number in sorted(numbers):
                if number in self._txns:
                    index.union(member, self._txn_member(number))
            receipt = msg.outcome.receipt_number
            if receipt is not None and receipt in self._receipts:
                index.union(member, self._receipt_member(receipt))
        for txn in self._b.transactions:
            index.add(self._txn_member(txn.number))
        for rcpt in self._b.receipts:
            index.add(self._receipt_member(rcpt.receipt_number))

    # --- amounts ---------------------------------------------------------------------------------

    def _request_amounts(self) -> tuple[set[str], set[str]]:
        """Register every amount; returns the transactions and receipts whose balance is derived."""
        m, p = self._mapper, self._p
        for msg in self._b.messages:
            mid = msg.message_id
            member = f"msg:{mid}"
            cur = (msg.payment_currency or "").upper()
            key = p.map(Kind.MESSAGE, mid)
            if msg.payment_amount is not None:
                m.request(f"h:{mid}", member, msg.payment_amount, cur, AmountGroup.HEADER, key)
            line_handles: list[str] = []
            for i, alloc in enumerate(msg.allocations):
                if alloc.applied_amount is not None:
                    handle = f"l:{mid}:{i}"
                    line_handles.append(handle)
                    m.request(
                        handle,
                        member,
                        alloc.applied_amount,
                        cur,
                        AmountGroup.LINE,
                        f"{key}:{i:04d}",
                    )
            if msg.payment_amount is not None:
                m.declare_sum(f"h:{mid}", line_handles)
            for i, line in enumerate(msg.outcome.lines):
                if line.applied_amount is not None:
                    m.request(
                        f"o:{mid}:{i}",
                        member,
                        line.applied_amount,
                        cur,
                        AmountGroup.LINE,
                        f"{key}:o{i:04d}",
                    )
        derived_txns: set[str] = set()
        for txn in self._b.transactions:
            member = self._txn_member(txn.number)
            key = p.map(Kind.INVOICE, txn.number)
            m.request(
                f"t:{txn.number}:o",
                member,
                txn.original_amount,
                txn.currency,
                AmountGroup.TRANSACTION,
                f"{key}:0",
            )
            apps = self._apps_by_txn.get(txn.number, [])
            applied = sum((a.amount_applied for a in apps), Decimal(0))
            if apps and money_eq(txn.original_amount - applied, txn.balance):
                derived_txns.add(txn.number)
            else:
                m.request(
                    f"t:{txn.number}:b",
                    member,
                    txn.balance,
                    txn.currency,
                    AmountGroup.TRANSACTION,
                    f"{key}:1",
                )
        derived_receipts: set[str] = set()
        for rcpt in self._b.receipts:
            member = self._receipt_member(rcpt.receipt_number)
            key = p.map(Kind.RECEIPT, rcpt.receipt_number)
            m.request(
                f"r:{rcpt.receipt_number}:a",
                member,
                rcpt.amount,
                rcpt.currency,
                AmountGroup.RECEIPT,
                f"{key}:0",
            )
            apps = self._apps_by_receipt.get(rcpt.receipt_number, [])
            applied = sum((a.amount_applied for a in apps), Decimal(0))
            if apps and money_eq(rcpt.amount - applied, rcpt.unapplied_amount):
                derived_receipts.add(rcpt.receipt_number)
            else:
                m.request(
                    f"r:{rcpt.receipt_number}:u",
                    member,
                    rcpt.unapplied_amount,
                    rcpt.currency,
                    AmountGroup.RECEIPT,
                    f"{key}:1",
                )
        for i, app in enumerate(self._b.applications):
            receipt = self._receipts[app.receipt_number]
            key = (
                f"{p.map(Kind.RECEIPT, app.receipt_number)}:"
                f"{p.map(Kind.INVOICE, app.transaction_number)}:"
                f"{app.amount_applied}:{app.apply_date}"
            )
            m.request(
                f"p:{i}",
                self._receipt_member(app.receipt_number),
                app.amount_applied,
                receipt.currency,
                AmountGroup.APPLICATION,
                key,
            )
        for failure in self._b.failures:
            member = f"msg:{failure.message_id}"
            cur = self._currency_by_message[failure.message_id]
            key = p.map(Kind.MESSAGE, failure.message_id)
            if failure.fusion_amount is not None:
                m.request(
                    f"f:{failure.message_id}",
                    member,
                    failure.fusion_amount,
                    cur,
                    AmountGroup.LABEL,
                    key,
                )
            for i, label in enumerate(failure.lines):
                if label.fusion_amount is not None:
                    m.request(
                        f"fl:{failure.message_id}:{i}",
                        member,
                        label.fusion_amount,
                        cur,
                        AmountGroup.LABEL,
                        f"{key}:{i:04d}",
                    )
        return derived_txns, derived_receipts

    def _out(self, handle: str) -> Decimal | None:
        return self._mapper.mapped_optional(handle)

    # --- outputs ---------------------------------------------------------------------------------

    def _extraction(self, msg: SourceMessage) -> RemittanceExtraction:
        p = self._p
        mid = msg.message_id
        raw_currency = msg.payment_currency
        code = raw_currency.strip().upper() if raw_currency else None
        iso = code if code is not None and is_iso_4217(code) else None
        payment_date = p.shift_date(msg.payment_date).isoformat() if msg.payment_date else None
        lines: list[_Json] = []
        for i, alloc in enumerate(msg.allocations):
            lines.append(self._line(msg, i, alloc))
        document: _Json = {
            "payer_name": _present(None),
            "payer_bank_account": _present(p.map_optional(Kind.BANK, msg.payer_bank_account)),
            "remittance_reference": _present(p.map_optional(Kind.REFERENCE, msg.reference_number)),
            "payment_amount": _present(_fmt(self._out(f"h:{mid}"))),
            "currency_raw": _present(raw_currency),
            "currency": _present(iso),
            "currency_ambiguous": False,
            "dates": (
                [
                    {
                        "value": payment_date,
                        "kind": "payment",
                        "source": dict(_SOURCE),
                        "confidence": 1.0,
                    }
                ]
                if payment_date
                else []
            ),
            "payment_date": _present(payment_date),
            "lines": lines,
            "po_refs": [p.map(Kind.PURCHASE_ORDER, v) for v in msg.po_refs],
            "sales_order_refs": [p.map(Kind.SALES_ORDER, v) for v in msg.sales_order_refs],
            "ers_refs": [p.map(Kind.ERS, v) for v in msg.ers_refs],
            "bank_fees": [],
            "notes": None,
        }
        return RemittanceExtraction.model_validate(document)

    def _line(self, msg: SourceMessage, index: int, alloc: SourceAllocation) -> _Json:
        p = self._p
        return {
            "line_no": index + 1,
            "kind": (LineKind.CREDIT_MEMO if alloc.credit_memo else LineKind.INVOICE).value,
            "transaction_number": p.map(Kind.INVOICE, alloc.transaction_number),
            "amount_paid": _fmt(self._out(f"l:{msg.message_id}:{index}")),
            "po_number": p.map_optional(Kind.PURCHASE_ORDER, alloc.po_number),
            "sales_order": p.map_optional(Kind.SALES_ORDER, alloc.sales_order),
            "ers_reference": p.map_optional(Kind.ERS, alloc.ers_reference),
            "source": dict(_SOURCE),
            "confidence": 1.0,
        }

    def _prior_message(self, msg: SourceMessage) -> PriorMessage:
        p = self._p
        mid = msg.message_id
        outcome = PriorOutcome(
            payment_status=msg.outcome.payment_status,
            lines=[
                OutcomeLine(
                    transaction_number=p.map(Kind.INVOICE, line.transaction_number),
                    line_status=line.line_status,
                    applied_amount=self._out(f"o:{mid}:{i}"),
                )
                for i, line in enumerate(msg.outcome.lines)
            ],
            receipt_number=p.map_optional(Kind.RECEIPT, msg.outcome.receipt_number),
        )
        return PriorMessage(
            message_id=p.map(Kind.MESSAGE, mid), extraction=self._extraction(msg), outcome=outcome
        )

    def _failures(self) -> list[PriorFailure]:
        p = self._p
        rows = [
            PriorFailure(
                message_id=p.map(Kind.MESSAGE, f.message_id),
                label=f.label,
                fusion_amount=self._out(f"f:{f.message_id}"),
                line_labels=[
                    LineLabel(
                        transaction_number=p.map(Kind.INVOICE, label.transaction_number),
                        label=label.label,
                        fusion_amount=self._out(f"fl:{f.message_id}:{i}"),
                    )
                    for i, label in enumerate(f.lines)
                ],
            )
            for f in self._b.failures
        ]
        return sorted(rows, key=lambda row: row.message_id)

    def _fusion(self, derived_txns: set[str], derived_receipts: set[str]) -> _Json:
        p, m = self._p, self._mapper
        txns = sorted(self._b.transactions, key=lambda t: p.map(Kind.INVOICE, t.number))
        txn_ids = {t.number: FIRST_TRANSACTION_ID + i for i, t in enumerate(txns)}
        receipts = sorted(self._b.receipts, key=lambda r: p.map(Kind.RECEIPT, r.receipt_number))
        receipt_ids = {r.receipt_number: FIRST_RECEIPT_ID + i for i, r in enumerate(receipts)}
        index_of = {id(a): i for i, a in enumerate(self._b.applications)}
        apps = sorted(
            self._b.applications,
            key=lambda a: (
                p.map(Kind.RECEIPT, a.receipt_number),
                p.map(Kind.INVOICE, a.transaction_number),
                m.mapped(f"p:{index_of[id(a)]}"),
                p.shift_date(a.apply_date),
            ),
        )

        def txn_balance(t: SourceTransaction) -> Decimal:
            if t.number in derived_txns:
                applied = sum(
                    (m.mapped(f"p:{index_of[id(a)]}") for a in self._apps_by_txn[t.number]),
                    Decimal(0),
                )
                return m.mapped(f"t:{t.number}:o") - applied
            return m.mapped(f"t:{t.number}:b")

        def receipt_unapplied(r: SourceReceipt) -> Decimal:
            if r.receipt_number in derived_receipts:
                applied = sum(
                    (
                        m.mapped(f"p:{index_of[id(a)]}")
                        for a in self._apps_by_receipt[r.receipt_number]
                    ),
                    Decimal(0),
                )
                return m.mapped(f"r:{r.receipt_number}:a") - applied
            return m.mapped(f"r:{r.receipt_number}:u")

        return {
            "customers": [
                {
                    "account_number": p.map(Kind.ACCOUNT, c.account_number),
                    "name": p.map(Kind.CUSTOMER_NAME, c.name),
                    "currency_codes": list(c.currency_codes),
                    "sites": [],
                }
                for c in sorted(
                    self._b.customers, key=lambda c: p.map(Kind.ACCOUNT, c.account_number)
                )
            ],
            "transactions": [
                {
                    "customer_trx_id": txn_ids[t.number],
                    "number": p.map(Kind.INVOICE, t.number),
                    "kind": t.kind,
                    "balance": _fmt(txn_balance(t)),
                    "original_amount": _fmt(m.mapped(f"t:{t.number}:o")),
                    "currency": t.currency,
                    "status": t.status,
                    "bill_to_customer_number": p.map_optional(
                        Kind.ACCOUNT, t.bill_to_customer_number
                    ),
                    "bill_to_site": p.map_optional(Kind.SITE, t.bill_to_site),
                    "business_unit": p.map_optional(Kind.BUSINESS_UNIT, t.business_unit),
                    "payment_terms": p.map_optional(Kind.TERMS, t.payment_terms),
                }
                for t in txns
            ],
            "receipts": [
                {
                    "receipt_id": receipt_ids[r.receipt_number],
                    "receipt_number": p.map(Kind.RECEIPT, r.receipt_number),
                    "amount": _fmt(m.mapped(f"r:{r.receipt_number}:a")),
                    "unapplied_amount": _fmt(receipt_unapplied(r)),
                    "currency": r.currency,
                    "customer_account_number": p.map_optional(
                        Kind.ACCOUNT, r.customer_account_number
                    ),
                    "receipt_date": p.shift_date(r.receipt_date).isoformat(),
                    "creation_date": p.shift_datetime(r.creation_date).isoformat(),
                    "status": r.status,
                    "state": r.state,
                    "remittance_references": [
                        p.map(Kind.REFERENCE, ref) for ref in r.remittance_references
                    ],
                    "comments": p.scrub_text(r.comments),
                }
                for r in receipts
            ],
            "applications": [
                {
                    "application_id": FIRST_APPLICATION_ID + i,
                    "receipt_id": receipt_ids[a.receipt_number],
                    "customer_trx_id": txn_ids[a.transaction_number],
                    "amount_applied": _fmt(m.mapped(f"p:{index_of[id(a)]}")),
                    "apply_date": p.shift_date(a.apply_date).isoformat(),
                    "status": "APP",
                }
                for i, a in enumerate(apps)
            ],
            "relationships": [
                {
                    "account_number": a,
                    "related_account_number": b,
                    "related_account_name": None,
                    "directions": list(_BOTH_DIRECTIONS),
                }
                for a, b in sorted(
                    {
                        (
                            p.map(Kind.ACCOUNT, r.account_number),
                            p.map(Kind.ACCOUNT, r.related_account_number),
                        )
                        for r in self._b.relationships
                    }
                )
            ],
            "reports": {},
        }

    def run(self) -> PriorFixtures:
        self._build_clusters()
        derived_txns, derived_receipts = self._request_amounts()
        self._mapper.resolve()
        messages = sorted(
            (self._prior_message(m) for m in self._b.messages), key=lambda x: x.message_id
        )
        fusion = self._fusion(derived_txns, derived_receipts)
        failures = self._failures()
        counts = {
            "messages": len(messages),
            "lines": sum(len(x.extraction.lines) for x in messages),
            "customers": len(self._b.customers),
            "transactions": len(self._b.transactions),
            "receipts": len(self._b.receipts),
            "applications": len(self._b.applications),
            "relationships": len(self._b.relationships),
            "failures": len(failures),
            "clusters": len(self._index),
            "numeric_ids_coerced": self._b.numeric_ids_coerced,
        }
        manifest = PriorManifest(
            format_version=FORMAT_VERSION,
            synthetic=False,
            seed=None,
            key_id=key_id(self._key),
            generated_by=GENERATED_BY,
            counts=counts,
        )
        return PriorFixtures(messages=messages, fusion=fusion, failures=failures, manifest=manifest)
