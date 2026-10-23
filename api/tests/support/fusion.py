"""`FusionScenario`: a fluent builder for a `FakeFusionClient` ledger.

Tests either import the fixtures (`from tests.support.fusion import fusion_scenario, fake_fusion`)
or build a scenario directly. IDs are deterministic: transactions from 100001, receipts from 500001.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import pytest

from cashapp.domain.money import to_money
from cashapp.integrations.fusion.fake import FakeFusionClient
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.models import (
    CustomerRelationship,
    FusionApplication,
    FusionCustomer,
    FusionCustomerSite,
    FusionReceipt,
    FusionTransaction,
    TransactionKind,
)

_BOTH = frozenset({"INBOUND", "OUTBOUND"})
_FIRST_TRX_ID = 100001
_FIRST_RECEIPT_ID = 500001
_FIRST_APPLICATION_ID = 900001


def _m(value: str | Decimal) -> Decimal:
    return to_money(value)


class FusionScenario:
    def __init__(self) -> None:
        self._customers: dict[str, FusionCustomer] = {}
        self._transactions: dict[str, FusionTransaction] = {}  # keyed by number+kind
        self._receipts: dict[str, FusionReceipt] = {}
        self._applications: list[FusionApplication] = []
        self._relationships: list[CustomerRelationship] = []
        self._reports: dict[str, bytes] = {}

    def customer(
        self,
        account_number: str,
        *,
        name: str | None = None,
        currencies: Sequence[str] = ("USD",),
        sites: Sequence[FusionCustomerSite] = (),
    ) -> Self:
        self._customers[account_number] = FusionCustomer(
            account_number=account_number,
            name=name or f"Customer {account_number}",
            currency_codes=tuple(currencies),
            sites=tuple(sites),
        )
        return self

    def invoice(
        self,
        number: str,
        amount: str | Decimal,
        *,
        customer: str,
        currency: str = "USD",
        balance: str | Decimal | None = None,
        status: str = "Open",
        terms: str | None = None,
        business_unit: str = "BU1",
        bill_to_site: str | None = None,
    ) -> Self:
        original = _m(amount)
        self._transactions[f"{number}|{TransactionKind.INVOICE}"] = FusionTransaction(
            customer_trx_id=_FIRST_TRX_ID + len(self._transactions),
            number=number,
            kind=TransactionKind.INVOICE,
            balance=original if balance is None else _m(balance),
            original_amount=original,
            currency=currency,
            status=status,
            bill_to_customer_number=customer,
            bill_to_site=bill_to_site,
            business_unit=business_unit,
            payment_terms=terms,
        )
        return self

    def credit_memo(
        self,
        number: str,
        amount: str | Decimal,
        *,
        customer: str,
        currency: str = "USD",
        balance: str | Decimal | None = None,
        status: str = "Open",
    ) -> Self:
        original = -abs(_m(amount))
        self._transactions[f"{number}|{TransactionKind.CREDIT_MEMO}"] = FusionTransaction(
            customer_trx_id=_FIRST_TRX_ID + len(self._transactions),
            number=number,
            kind=TransactionKind.CREDIT_MEMO,
            balance=original if balance is None else -abs(_m(balance)),
            original_amount=original,
            currency=currency,
            status=status,
            bill_to_customer_number=customer,
            bill_to_site=None,
            business_unit="BU1",
            payment_terms=None,
        )
        return self

    def receipt(
        self,
        number: str,
        amount: str | Decimal,
        *,
        customer: str | None,
        receipt_date: date,
        currency: str = "USD",
        unapplied: str | Decimal | None = None,
        creation_date: datetime | None = None,
        references: Sequence[str] = (),
        status: str = "UNAPP",
        state: str = "CLEARED",
        comments: str | None = None,
    ) -> Self:
        total = _m(amount)
        self._receipts[number] = FusionReceipt(
            receipt_id=_FIRST_RECEIPT_ID + len(self._receipts),
            receipt_number=number,
            amount=total,
            unapplied_amount=total if unapplied is None else _m(unapplied),
            currency=currency,
            customer_account_number=customer,
            receipt_date=receipt_date,
            creation_date=creation_date
            or datetime(receipt_date.year, receipt_date.month, receipt_date.day, tzinfo=UTC),
            status=status,
            state=state,
            remittance_references=tuple(references),
            comments=comments,
        )
        return self

    def application(
        self,
        receipt_number: str,
        transaction_number: str,
        amount: str | Decimal,
        *,
        apply_date: date | None = None,
    ) -> Self:
        """Record an existing application and adjust balances as Fusion would."""
        receipt = self._receipts[receipt_number]
        key = next(k for k, t in self._transactions.items() if t.number == transaction_number)
        txn = self._transactions[key]
        applied = _m(amount)
        self._transactions[key] = replace(txn, balance=txn.balance - applied)
        self._receipts[receipt_number] = replace(
            receipt, unapplied_amount=receipt.unapplied_amount - applied
        )
        self._applications.append(
            FusionApplication(
                application_id=_FIRST_APPLICATION_ID + len(self._applications),
                receipt_id=receipt.receipt_id,
                customer_trx_id=txn.customer_trx_id,
                amount_applied=applied,
                apply_date=apply_date or receipt.receipt_date,
                status="APP",
            )
        )
        return self

    def relationship(self, account: str, related: str, *, name: str | None = None) -> Self:
        self._relationships.append(CustomerRelationship(account, related, name, _BOTH))  # pyright: ignore[reportArgumentType]
        return self

    def report(self, path: str, content: bytes) -> Self:
        self._reports[path] = content
        return self

    def build(
        self, *, guard: WriteGuard | None = None, today: date | None = None
    ) -> FakeFusionClient:
        return FakeFusionClient(
            transactions=self._transactions.values(),
            receipts=self._receipts.values(),
            applications=self._applications,
            customers=self._customers.values(),
            relationships=self._relationships,
            reports=self._reports,
            guard=guard,
            today=(lambda: today) if today is not None else None,
        )

    def to_json(self) -> dict[str, Any]:
        return self.build().to_json()


def load_scenario(path: str | Path) -> FusionScenario:
    """Load a scenario JSON file (the shape `to_json` writes) into a builder."""
    client = FakeFusionClient.from_json(json.loads(Path(path).read_text(encoding="utf-8")))
    scenario = FusionScenario()
    document = client.to_json()
    for customer in document["customers"]:
        scenario._customers[customer["account_number"]] = FusionCustomer(  # pyright: ignore[reportPrivateUsage]
            account_number=customer["account_number"],
            name=customer["name"],
            currency_codes=tuple(customer["currency_codes"]),
            sites=tuple(FusionCustomerSite(**site) for site in customer["sites"]),
        )
    return _populate(scenario, client)


def _populate(scenario: FusionScenario, client: FakeFusionClient) -> FusionScenario:
    document = client.to_json()
    scenario._transactions = {  # pyright: ignore[reportPrivateUsage]
        f"{t['number']}|{t['kind']}": client.transaction(t["number"], TransactionKind(t["kind"]))
        for t in document["transactions"]
    }
    scenario._receipts = {  # pyright: ignore[reportPrivateUsage]
        r["receipt_number"]: client.receipt(r["receipt_id"]) for r in document["receipts"]
    }
    scenario._applications = client.applications()  # pyright: ignore[reportPrivateUsage]
    scenario._relationships = [  # pyright: ignore[reportPrivateUsage]
        CustomerRelationship(
            r["account_number"],
            r["related_account_number"],
            r["related_account_name"],
            frozenset(r["directions"]),
        )
        for r in document["relationships"]
    ]
    scenario._reports = {k: v.encode("utf-8") for k, v in document["reports"].items()}  # pyright: ignore[reportPrivateUsage]
    return scenario


@pytest.fixture
def fusion_scenario() -> FusionScenario:
    return FusionScenario()


@pytest.fixture
def fake_fusion(fusion_scenario: FusionScenario) -> FakeFusionClient:
    return fusion_scenario.build()
