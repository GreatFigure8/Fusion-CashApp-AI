"""A fake source folder in exactly the shape ``load_source`` reads.

Everything comes from ``random.Random(seed)`` and fixed dates (no wall clock), so the same seed
always writes the same bytes. Names are obviously fake, emails use a reserved domain, and a fixed
set of scenarios is always present so tests and the eval harness run before real data arrives.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from cashapp.tools.anonymise.fixture_format import PriorLabel
from cashapp.tools.anonymise.source import (
    APPLICATIONS_FILE,
    CUSTOMERS_FILE,
    FAILURES_FILE,
    MESSAGES_FILE,
    RECEIPTS_FILE,
    RELATIONSHIPS_FILE,
    TRANSACTIONS_FILE,
)

DAY: Final = date(2026, 3, 4)  # the production day the messages arrived
WEEK_START: Final = date(2026, 3, 2)
GUARANTEED_MESSAGES: Final = 15

_D = Decimal
_INVOICE: Final = "Payment"
_CREDIT_MEMO: Final = "Credit Memo"


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}"


@dataclass
class _Txn:
    number: str
    kind: str
    original: Decimal
    currency: str
    account: str
    balance: Decimal = Decimal(0)
    site: str = ""
    unit: str = "Synthetic Unit A"
    terms: str = "NET 30"


@dataclass
class _Receipt:
    number: str
    amount: Decimal
    currency: str
    account: str
    receipt_date: date
    creation: datetime
    refs: str = ""
    comments: str = ""
    bank: str = ""
    unapplied: Decimal = Decimal(0)


@dataclass
class _World:
    rng: random.Random
    customers: list[tuple[str, str, str]] = field(default_factory=lambda: [])
    txns: dict[str, _Txn] = field(default_factory=lambda: {})
    receipts: dict[str, _Receipt] = field(default_factory=lambda: {})
    apps: list[tuple[str, str, Decimal, date]] = field(default_factory=lambda: [])
    relationships: list[tuple[str, str]] = field(default_factory=lambda: [])
    messages: list[dict[str, Any]] = field(default_factory=lambda: [])
    failure_rows: list[list[str]] = field(default_factory=lambda: [])
    used: set[str] = field(default_factory=lambda: set())

    # --- identifiers -----------------------------------------------------------------------------

    def _unique(self, low: int, high: int, prefix: str = "") -> str:
        while True:
            candidate = f"{prefix}{self.rng.randint(low, high)}"
            if candidate not in self.used:
                self.used.add(candidate)
                return candidate

    def customer(self, currency: str = "USD") -> tuple[str, str]:
        digits = self.rng.choice([4, 5, 6, 7, 8, 9])
        account = self._unique(10 ** (digits - 1), 10**digits - 1)
        name = f"Synthetic Payer {len(self.customers) + 1:03d}"
        self.customers.append((account, name, currency))
        return account, name

    def number(self) -> str:
        return self._unique(1_000_000, 99_999_999)

    def amount(self, low: int = 50, high: int = 9_000) -> Decimal:
        return _D(self.rng.randint(low * 100, high * 100)) / 100

    def pay_date(self) -> date:
        return WEEK_START + timedelta(days=self.rng.randint(0, 2))

    # --- ledger ----------------------------------------------------------------------------------

    def invoice(
        self, account: str, amount: Decimal, currency: str = "USD", number: str | None = None
    ) -> str:
        number = number or self.number()
        self.txns[number] = _Txn(number, "INVOICE", amount, currency, account, amount)
        return number

    def credit_memo(self, account: str, number: str, amount: Decimal, currency: str = "USD") -> str:
        self.txns[number] = _Txn(
            number, "CREDIT_MEMO", -abs(amount), currency, account, -abs(amount)
        )
        return number

    def receipt(
        self,
        account: str,
        amount: Decimal,
        paid: date,
        currency: str = "USD",
        comments: str = "",
        bank: str = "",
    ) -> str:
        number = self._unique(10_000_000, 99_999_999, "R")
        creation = datetime(paid.year, paid.month, paid.day, 9, 0, tzinfo=UTC) + timedelta(
            days=self.rng.randint(0, 1)
        )
        ref = self._unique(100_000, 999_999, "SYNREF")
        self.receipts[number] = _Receipt(
            number, amount, currency, account, paid, creation, ref, comments, bank, amount
        )
        return number

    def apply(self, receipt: str, txn: str, amount: Decimal, when: date) -> None:
        self.receipts[receipt].unapplied -= amount
        self.txns[txn].balance -= amount
        self.apps.append((receipt, txn, amount, when))

    # --- messages --------------------------------------------------------------------------------

    def message(
        self,
        payer: str,
        paid: date,
        currency: str,
        allocations: list[dict[str, Any]],
        *,
        header: Decimal | None,
        status: str,
        outcome_lines: list[dict[str, Any]],
        receipt: str | None,
        bank: str | None = None,
    ) -> str:
        message_id = f"synthetic-msg-{len(self.messages) + 1:04d}"
        payment: dict[str, Any] = {
            "reference_number": self._unique(100_000, 999_999, "SYNPAY"),
            "payment_amount": None if header is None else self.number_value(header),
            "payment_date": paid.isoformat(),
            "payment_currency": currency,
            "allocations": allocations,
        }
        payload: dict[str, Any] = {
            "payerName": payer.upper(),
            "payerEmail": f"synth-{len(self.messages) + 1:03d}@example.com",
            "payments": [payment],
            "paymentSummary": f"Payment from {payer} for settlement",
            "status": status,
            "statusDescription": f"{payer} remittance processed",
        }
        if bank is not None:
            payload["payerBankAccount"] = bank
        self.messages.append(
            {
                "message_id": message_id,
                "payload": payload,
                "outcome": {
                    "payment_status": status,
                    "lines": outcome_lines,
                    "receipt_number": receipt,
                },
            }
        )
        return message_id

    def number_value(self, value: Decimal) -> float | str:
        """Amounts alternate between JSON numbers and strings, as the old contract mixed both."""
        return float(value) if self.rng.random() < 0.5 else _fmt(value)

    def alloc(
        self, number: str | int, amount: Decimal | None, *, credit_memo: bool = False
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "application_type": _CREDIT_MEMO if credit_memo else _INVOICE,
            "invoice_number": None if credit_memo else number,
            "credit_memo_id": number if credit_memo else None,
            "applied_amount": None if amount is None else self.number_value(amount),
        }
        return item

    def line(self, number: str | int, status: str, amount: Decimal | None) -> dict[str, Any]:
        return {
            "invoice_number": number,
            "line_status": status,
            "applied_amount": None if amount is None else self.number_value(amount),
        }


def _success(world: _World, payer_currency: str = "USD") -> None:
    """A plain fully applied remittance."""
    account, name = world.customer(payer_currency)
    paid = world.pay_date()
    amounts = [world.amount() for _ in range(world.rng.randint(1, 3))]
    numbers = [world.invoice(account, a, payer_currency) for a in amounts]
    total = sum(amounts, _D(0))
    receipt = world.receipt(account, total, paid, payer_currency)
    for number, amount in zip(numbers, amounts, strict=True):
        world.apply(receipt, number, amount, paid)
    world.message(
        name,
        paid,
        payer_currency,
        [world.alloc(n, a) for n, a in zip(numbers, amounts, strict=True)],
        header=total,
        status="payment-success",
        outcome_lines=[
            world.line(n, "allocation-applied", a) for n, a in zip(numbers, amounts, strict=True)
        ],
        receipt=receipt,
    )


def _credit_memos(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    base = world.number()
    invoice = world.invoice(account, _D("1200.00"), number=base)
    memo1 = world.credit_memo(account, f"{base}-1", _D("100.00"))
    memo2 = world.credit_memo(account, f"{base}-2", _D("50.25"))
    comment = f"Remitted by {name} contact synth-001@example.com ref {paid:%Y%m%d}"
    receipt = world.receipt(account, _D("1049.75"), paid, comments=comment, bank="SYNBANK0001")
    world.apply(receipt, invoice, _D("1200.00"), paid)
    world.apply(receipt, memo1, _D("-100.00"), paid)
    world.apply(receipt, memo2, _D("-50.25"), paid)
    world.message(
        name,
        paid,
        "USD",
        [
            world.alloc(invoice, _D("1200.00")),
            world.alloc(memo1, _D("-100.00"), credit_memo=True),
            world.alloc(memo2, _D("-50.25"), credit_memo=True),
        ],
        header=_D("1049.75"),
        status="payment-success",
        outcome_lines=[
            world.line(invoice, "allocation-applied", _D("1200.00")),
            world.line(memo1, "allocation-applied", _D("-100.00")),
            world.line(memo2, "allocation-applied", _D("-50.25")),
        ],
        receipt=receipt,
        bank="SYNBANK0001",
    )


def _numeric_invoice_number(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    number = int(world.number())
    amount = _D("845.10")
    world.invoice(account, amount, number=str(number))
    receipt = world.receipt(account, amount, paid)
    world.apply(receipt, str(number), amount, paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(number, amount)],
        header=amount,
        status="payment-success",
        outcome_lines=[world.line(number, "allocation-applied", amount)],
        receipt=receipt,
    )


def _no_amount_line(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    paid_invoice = world.invoice(account, _D("300.00"))
    other = world.invoice(account, _D("200.00"))
    receipt = world.receipt(account, _D("300.00"), paid)
    world.apply(receipt, paid_invoice, _D("300.00"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(paid_invoice, _D("300.00")), world.alloc(other, None)],
        header=_D("300.00"),
        status="payment-success",
        outcome_lines=[
            world.line(paid_invoice, "allocation-applied", _D("300.00")),
            world.line(other, "allocation-zero-amount", None),
        ],
        receipt=receipt,
    )


def _header_not_sum(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    first = world.invoice(account, _D("450.00"))
    second = world.invoice(account, _D("30.00"))
    receipt = world.receipt(account, _D("500.00"), paid)
    world.apply(receipt, first, _D("450.00"), paid)
    world.apply(receipt, second, _D("30.00"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(first, _D("450.00")), world.alloc(second, _D("30.00"))],
        header=_D("500.00"),
        status="payment-less-than-total-due-success",
        outcome_lines=[
            world.line(first, "allocation-applied", _D("450.00")),
            world.line(second, "allocation-applied", _D("30.00")),
        ],
        receipt=receipt,
    )


def _inr_whole_rupee(world: _World) -> None:
    account, name = world.customer("INR")
    paid = world.pay_date()
    first = world.invoice(account, _D("62500.50"), "INR")
    second = world.invoice(account, _D("62499.50"), "INR")
    receipt = world.receipt(account, _D("125000.00"), paid, "INR")
    world.apply(receipt, first, _D("62500.50"), paid)
    world.apply(receipt, second, _D("62499.50"), paid)
    world.message(
        name,
        paid,
        "INR",
        [world.alloc(first, _D("62500.50")), world.alloc(second, _D("62499.50"))],
        header=_D("125000.00"),
        status="payment-success",
        outcome_lines=[
            world.line(first, "allocation-applied", _D("62500.50")),
            world.line(second, "allocation-applied", _D("62499.50")),
        ],
        receipt=receipt,
    )


def _bank_fee_residual(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    invoice = world.invoice(account, _D("800.00"))
    receipt = world.receipt(account, _D("799.93"), paid)
    world.apply(receipt, invoice, _D("799.93"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(invoice, _D("799.93"))],
        header=_D("799.93"),
        status="payment-success",
        outcome_lines=[
            world.line(invoice, "allocation-applied-less-than-instruction", _D("799.93"))
        ],
        receipt=receipt,
    )


def _short_pay(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    invoice = world.invoice(account, _D("1000.00"))
    receipt = world.receipt(account, _D("900.00"), paid)
    world.apply(receipt, invoice, _D("900.00"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(invoice, _D("900.00"))],
        header=_D("900.00"),
        status="payment-success",
        outcome_lines=[world.line(invoice, "allocation-applied-short-pay", _D("900.00"))],
        receipt=receipt,
    )


def _pay_on_behalf(world: _World) -> None:
    payer, payer_name = world.customer()
    owner, _owner_name = world.customer()
    paid = world.pay_date()
    invoice = world.invoice(owner, _D("2750.00"))
    receipt = world.receipt(payer, _D("2750.00"), paid)
    world.relationships.append((payer, owner))
    world.apply(receipt, invoice, _D("2750.00"), paid)
    world.message(
        payer_name,
        paid,
        "USD",
        [world.alloc(invoice, _D("2750.00"))],
        header=_D("2750.00"),
        status="payment-success",
        outcome_lines=[world.line(invoice, "allocation-applied", _D("2750.00"))],
        receipt=receipt,
    )


def _customer_not_found(world: _World) -> None:
    paid = world.pay_date()
    numbers = [world.number(), world.number()]
    world.message(
        "Synthetic Payer Unknown",
        paid,
        "USD",
        [world.alloc(numbers[0], _D("410.00")), world.alloc(numbers[1], _D("90.00"))],
        header=_D("500.00"),
        status="customer-not-found",
        outcome_lines=[
            world.line(numbers[0], "allocation-customer-not-found", None),
            world.line(numbers[1], "allocation-customer-not-found", None),
        ],
        receipt=None,
    )


def _duplicate_invoice(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    invoice = world.invoice(account, _D("150.00"))
    receipt = world.receipt(account, _D("300.00"), paid)
    world.apply(receipt, invoice, _D("150.00"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(invoice, _D("150.00")), world.alloc(invoice, _D("150.00"))],
        header=_D("300.00"),
        status="payment-less-than-total-due-success",
        outcome_lines=[
            world.line(invoice, "allocation-applied", _D("150.00")),
            world.line(invoice, "allocation-no-remaining-balance", None),
        ],
        receipt=receipt,
    )


def _apply_failed(world: _World) -> None:
    account, name = world.customer()
    paid = world.pay_date()
    invoice = world.invoice(account, _D("640.00"))
    receipt = world.receipt(account, _D("640.00"), paid)
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(invoice, _D("640.00"))],
        header=_D("640.00"),
        status="payment-apply-failed",  # the old catch-all status; STATUS_ALIASES maps it
        outcome_lines=[world.line(invoice, "allocation-apply-failed", None)],
        receipt=receipt,
    )


def _labelled_failure(world: _World, label: PriorLabel) -> None:
    """A receipt-not-found payment carrying one of AR's four labels."""
    account, name = world.customer()
    future = label is PriorLabel.FUTURE
    paid = DAY + timedelta(days=2) if future else DAY - timedelta(days=world.rng.randint(0, 2))
    amounts = [world.amount(100, 600), world.amount(100, 600)]
    numbers = [world.invoice(account, a) for a in amounts]
    total = sum(amounts, _D(0))
    receipt: str | None = None
    if label is PriorLabel.RECEIPT_IN_FUSION:
        receipt = world.receipt(account, total, paid)
    message_id = world.message(
        name,
        paid,
        "USD",
        [world.alloc(n, a) for n, a in zip(numbers, amounts, strict=True)],
        header=total,
        status="receipt-not-found",
        outcome_lines=[world.line(n, "allocation-no-receipt-match", None) for n in numbers],
        receipt=receipt,
    )
    in_fusion = label is PriorLabel.RECEIPT_IN_FUSION
    for number, amount in zip(numbers, amounts, strict=True):
        world.failure_rows.append(
            [
                message_id,
                label.value,
                _fmt(total) if in_fusion else "",
                number,
                label.value,
                _fmt(amount) if in_fusion else "",
            ]
        )


def _invoice_not_found(world: _World) -> None:
    _account, name = world.customer()
    paid = world.pay_date()
    missing = world.number()
    world.message(
        name,
        paid,
        "USD",
        [world.alloc(missing, world.amount())],
        header=None,
        status="invoice-not-found",
        outcome_lines=[world.line(missing, "allocation-invoice-not-found", None)],
        receipt=None,
    )


_GUARANTEED = (
    _credit_memos,
    _numeric_invoice_number,
    _no_amount_line,
    _header_not_sum,
    _inr_whole_rupee,
    _bank_fee_residual,
    _short_pay,
    _pay_on_behalf,
    _customer_not_found,
    _duplicate_invoice,
    _apply_failed,
)
_LABELS = (
    PriorLabel.RECEIPT_IN_FUSION,
    PriorLabel.NOT_YET_ENTERED,
    PriorLabel.FUTURE,
    PriorLabel.NOT_IN_FUSION,
)


def _fill(world: _World) -> None:
    roll = world.rng.random()
    if roll < 0.70:
        _success(world)
    elif roll < 0.90:
        _labelled_failure(world, world.rng.choice(_LABELS))
    else:
        _invoice_not_found(world)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_synthetic_source(directory: Path, *, seed: int = 43, messages: int = 40) -> None:
    """Write a fake source folder. ``messages`` is raised to the 15 guaranteed scenarios."""
    world = _World(random.Random(seed))  # noqa: S311 - fake data, not security
    for scenario in _GUARANTEED:
        scenario(world)
    for label in _LABELS:
        _labelled_failure(world, label)
    while len(world.messages) < max(messages, GUARANTEED_MESSAGES):
        _fill(world)

    directory.mkdir(parents=True, exist_ok=True)
    with (directory / MESSAGES_FILE).open("w", encoding="utf-8", newline="") as handle:
        for row in world.messages:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    _write_csv(
        directory / CUSTOMERS_FILE,
        ["account_number", "name", "currency_codes"],
        [[account, name, currency] for account, name, currency in world.customers],
    )
    _write_csv(
        directory / TRANSACTIONS_FILE,
        [
            "number",
            "kind",
            "original_amount",
            "balance",
            "currency",
            "status",
            "bill_to_customer_number",
            "bill_to_site",
            "business_unit",
            "payment_terms",
        ],
        [
            [
                t.number,
                t.kind,
                _fmt(t.original),
                _fmt(t.balance),
                t.currency,
                "Closed" if t.balance == 0 else "Open",
                t.account,
                f"Synthetic Site {t.account[-3:]}",
                t.unit,
                t.terms,
            ]
            for t in world.txns.values()
        ],
    )
    _write_csv(
        directory / RECEIPTS_FILE,
        [
            "receipt_number",
            "amount",
            "unapplied_amount",
            "currency",
            "customer_account_number",
            "receipt_date",
            "creation_date",
            "status",
            "state",
            "remittance_references",
            "comments",
            "payer_bank_account",
        ],
        [
            [
                r.number,
                _fmt(r.amount),
                _fmt(r.unapplied),
                r.currency,
                r.account,
                r.receipt_date.isoformat(),
                r.creation.isoformat(),
                "APP" if r.unapplied == 0 else "UNAPP",
                "CLEARED",
                r.refs,
                r.comments,
                r.bank,
            ]
            for r in world.receipts.values()
        ],
    )
    _write_csv(
        directory / APPLICATIONS_FILE,
        ["receipt_number", "transaction_number", "amount_applied", "apply_date"],
        [[rcpt, txn, _fmt(amount), when.isoformat()] for rcpt, txn, amount, when in world.apps],
    )
    _write_csv(
        directory / RELATIONSHIPS_FILE,
        ["account_number", "related_account_number"],
        [[a, b] for a, b in world.relationships],
    )
    _write_csv(
        directory / FAILURES_FILE,
        [
            "message_id",
            "payment_label",
            "payment_fusion_amount",
            "transaction_number",
            "line_label",
            "line_fusion_amount",
        ],
        world.failure_rows,
    )
