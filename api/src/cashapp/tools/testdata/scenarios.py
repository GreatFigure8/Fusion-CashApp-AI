"""Scenario presets: each builds the Fusion data, the matching remittance and the expectation.

A preset implements only `build`; the `Scenario` base fills the remittance and validates the plan.
Amounts come from integer cents drawn from `random.Random(seed)`, so the same parameters always
give the same plan. No float is ever used for money.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Any, ClassVar, Final

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import DateKind, LineKind, RemittanceExtraction
from cashapp.domain.money import to_money
from cashapp.domain.status import LineStatus
from cashapp.tools.testdata.models import (
    Expected,
    ExpectedLine,
    PlannedApplication,
    PlannedReceipt,
    PlannedTransaction,
    ScenarioName,
    ScenarioParams,
    ScenarioPlan,
)
from cashapp.tools.testdata.tagging import number_prefix, tagged_number, validate_tag

_ZERO: Final = Decimal("0.00")
_MIN_CENTS: Final = 10_000
_MAX_CENTS: Final = 999_999
_INVOICE_AGE: Final = timedelta(days=30)
_SHORT_PAY_RATE: Final = Decimal("0.95")
_WHOLE_UNIT: Final = Decimal(1)
_INR_MAX_RESIDUAL: Final = Decimal("0.49")


@dataclass(frozen=True, slots=True)
class RemitLine:
    """One line of the synthetic remittance."""

    number: str
    kind: LineKind
    gross: Decimal
    paid: Decimal
    deduction: Decimal | None = None


@dataclass(frozen=True, slots=True)
class _Draft:
    """What a preset returns; the base class turns it into a `ScenarioPlan`."""

    params: ScenarioParams
    invoices: list[PlannedTransaction]
    receipts: list[PlannedReceipt]
    remit_lines: list[RemitLine]
    payment_amount: Decimal
    expected: Expected
    credit_memos: list[PlannedTransaction] = field(default_factory=list[PlannedTransaction])
    pre_applications: list[PlannedApplication] = field(default_factory=list[PlannedApplication])


# --- amount helpers -------------------------------------------------------------------------


def random_amount(rng: random.Random) -> Decimal:
    """A positive 2 dp amount in [100.00, 9999.99] from integer cents."""
    return to_money(Decimal(rng.randint(_MIN_CENTS, _MAX_CENTS)) / 100)


def random_amounts(rng: random.Random, count: int) -> list[Decimal]:
    return [random_amount(rng) for _ in range(count)]


def total(amounts: list[Decimal]) -> Decimal:
    return to_money(sum(amounts, _ZERO))


def reference_for(tag: str) -> str:
    return f"{number_prefix(tag)}REF"


def other_reference_for(tag: str) -> str:
    return f"{number_prefix(tag)}OTH"


def _invoices(
    tag: str, params: ScenarioParams, amounts: list[Decimal], terms: str | None = None
) -> list[PlannedTransaction]:
    return [
        PlannedTransaction(
            number=tagged_number(tag, "INV", index),
            amount=amount,
            currency=params.currency,
            terms=terms,
            transaction_date=params.as_of - _INVOICE_AGE,
        )
        for index, amount in enumerate(amounts, start=1)
    ]


def _receipt(
    tag: str,
    params: ScenarioParams,
    index: int,
    amount: Decimal,
    receipt_date: date,
    references: list[str] | None = None,
) -> PlannedReceipt:
    return PlannedReceipt(
        number=tagged_number(tag, "RCPT", index),
        amount=amount,
        currency=params.currency,
        receipt_date=receipt_date,
        references=references or [],
    )


def _full_lines(invoices: list[PlannedTransaction]) -> list[RemitLine]:
    return [RemitLine(i.number, LineKind.INVOICE, i.amount, i.amount) for i in invoices]


def _applied(
    invoices: list[PlannedTransaction],
    status: LineStatus = LineStatus.ALLOCATION_APPLIED,
) -> list[ExpectedLine]:
    return [
        ExpectedLine(number=i.number, line_status=status, applied_amount=i.amount) for i in invoices
    ]


def _prefixed(value: str, tag: str) -> bool:
    return value.startswith(number_prefix(tag))


# --- the Scenario base --------------------------------------------------------------------------


class Scenario(ABC):
    name: ClassVar[ScenarioName]

    def plan(self, params: ScenarioParams, *, tag: str, customer_account: str) -> ScenarioPlan:
        tag = validate_tag(tag)
        draft = self.build(params, tag=tag, customer_account=customer_account)
        plan = ScenarioPlan(
            scenario=self.name,
            tag=tag,
            params=draft.params,
            customer_account=customer_account,
            invoices=draft.invoices,
            credit_memos=draft.credit_memos,
            receipts=draft.receipts,
            pre_applications=draft.pre_applications,
            remittance=self._remittance(draft, tag),
            expected=draft.expected,
        )
        self._check(plan)
        return plan

    @abstractmethod
    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft: ...

    # -- remittance -----------------------------------------------------------------------------

    @staticmethod
    def _remittance(draft: _Draft, tag: str) -> RemittanceExtraction:
        params = draft.params
        source: dict[str, Any] = {"part_no": 1}

        def field_of(value: Any) -> dict[str, Any]:
            return {"value": value, "source": source, "confidence": 1.0}

        lines: list[dict[str, Any]] = [
            {
                "line_no": line_no,
                "kind": line.kind.value,
                "transaction_number": line.number,
                "amount_paid": line.paid,
                "gross_amount": line.gross,
                "deduction": line.deduction,
                "source": source,
                "confidence": 1.0,
            }
            for line_no, line in enumerate(draft.remit_lines, start=1)
        ]
        document: dict[str, Any] = {
            "payer_name": field_of(f"Synthetic Payer {params.seed}"),
            "payer_bank_account": field_of(None),
            "remittance_reference": field_of(reference_for(tag)),
            "payment_amount": field_of(draft.payment_amount),
            "currency_raw": field_of(params.currency),
            "currency": field_of(params.currency),
            "currency_ambiguous": False,
            "dates": [
                {
                    "value": params.as_of,
                    "kind": DateKind.PAYMENT.value,
                    "source": source,
                    "confidence": 1.0,
                }
            ],
            "payment_date": field_of(params.as_of),
            "lines": lines,
            "po_refs": [],
            "sales_order_refs": [],
            "ers_refs": [],
            "bank_fees": [],
        }
        return RemittanceExtraction.model_validate(document)

    # -- validation -----------------------------------------------------------------------------

    @staticmethod
    def _check(plan: ScenarioPlan) -> None:
        transactions = [*plan.invoices, *plan.credit_memos]
        numbers = [t.number for t in transactions] + [r.number for r in plan.receipts]
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"{plan.scenario}: record numbers are not unique")
        if not all(_prefixed(n, plan.tag) for n in numbers):
            raise ValueError(f"{plan.scenario}: a record number is not tagged")
        currencies = {t.currency for t in transactions} | {r.currency for r in plan.receipts}
        if currencies != {plan.params.currency}:
            raise ValueError(f"{plan.scenario}: currencies are not consistent")
        transaction_numbers = {t.number for t in transactions}
        receipt_numbers = {r.number for r in plan.receipts}
        for expected in plan.expected.lines:
            if expected.number not in transaction_numbers:
                raise ValueError(f"{plan.scenario}: expected line {expected.number} is not planned")
        if plan.expected.receipt_number is not None and (
            plan.expected.receipt_number not in receipt_numbers
        ):
            raise ValueError(f"{plan.scenario}: expected receipt is not planned")
        for application in plan.pre_applications:
            if (
                application.receipt_number not in receipt_numbers
                or application.transaction_number not in transaction_numbers
            ):
                raise ValueError(
                    f"{plan.scenario}: a pre-application points at an unplanned record"
                )


# --- presets ------------------------------------------------------------------------------------


class OneToOne(Scenario):
    name = ScenarioName.ONE_TO_ONE

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, 1))
        amount = invoices[0].amount
        receipt = _receipt(tag, params, 1, amount, params.as_of)
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[receipt],
            remit_lines=_full_lines(invoices),
            payment_amount=amount,
            expected=Expected(receipt_number=receipt.number, lines=_applied(invoices)),
        )


class SplitPayment(Scenario):
    name = ScenarioName.SPLIT_PAYMENT

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, params.lines))
        amount = total([i.amount for i in invoices])
        receipt = _receipt(tag, params, 1, amount, params.as_of)
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[receipt],
            remit_lines=_full_lines(invoices),
            payment_amount=amount,
            expected=Expected(receipt_number=receipt.number, lines=_applied(invoices)),
        )


class ShortPay(Scenario):
    name = ScenarioName.SHORT_PAY

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, params.lines))
        last = invoices[-1]
        short_paid = to_money(last.amount * _SHORT_PAY_RATE)
        paid = [i.amount for i in invoices[:-1]] + [short_paid]
        amount = total(paid)
        receipt = _receipt(tag, params, 1, amount, params.as_of)
        remit_lines = [
            *_full_lines(invoices[:-1]),
            RemitLine(
                last.number,
                LineKind.INVOICE,
                gross=last.amount,
                paid=short_paid,
                deduction=to_money(last.amount - short_paid),
            ),
        ]
        expected_lines = [
            *_applied(invoices[:-1]),
            ExpectedLine(
                number=last.number,
                line_status=LineStatus.ALLOCATION_APPLIED_SHORT_PAY,
                applied_amount=short_paid,
            ),
        ]
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[receipt],
            remit_lines=remit_lines,
            payment_amount=amount,
            expected=Expected(receipt_number=receipt.number, lines=expected_lines),
        )


class InrRounding(Scenario):
    name = ScenarioName.INR_ROUNDING

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        inr = params.model_copy(update={"currency": "INR"})
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        amounts = [
            to_money(Decimal(rng.randint(100, 9_999)) + Decimal(rng.randint(1, 99)) / 100)
            for _ in range(inr.lines)
        ]
        # The residual must be real (not zero) and within the INR tolerance (not exactly 0.50).
        while (amounts_total := total(amounts)) % _WHOLE_UNIT in (_ZERO, Decimal("0.50")):
            amounts[-1] = to_money(amounts[-1] + Decimal("0.01"))
            if amounts[-1] % _WHOLE_UNIT == _ZERO:
                amounts[-1] = to_money(amounts[-1] + Decimal("0.01"))
        invoices = _invoices(tag, inr, amounts)
        receipt_amount = to_money(amounts_total.quantize(_WHOLE_UNIT, rounding=ROUND_HALF_UP))
        residual = to_money(receipt_amount - amounts_total)
        if residual == _ZERO or abs(residual) > _INR_MAX_RESIDUAL:
            raise ValueError("inr_rounding produced a residual outside 0.01..0.49")
        receipt = _receipt(tag, inr, 1, receipt_amount, inr.as_of)
        return _Draft(
            params=inr,
            invoices=invoices,
            receipts=[receipt],
            remit_lines=_full_lines(invoices),
            payment_amount=receipt_amount,
            expected=Expected(
                receipt_number=receipt.number, lines=_applied(invoices), residual=residual
            ),
        )


class DuplicateAmounts(Scenario):
    name = ScenarioName.DUPLICATE_AMOUNTS

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, params.lines))
        amount = total([i.amount for i in invoices])
        wanted = _receipt(tag, params, 1, amount, params.as_of, [reference_for(tag)])
        decoy = _receipt(
            tag, params, 2, amount, params.as_of - timedelta(days=20), [other_reference_for(tag)]
        )
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[wanted, decoy],
            remit_lines=_full_lines(invoices),
            payment_amount=amount,
            expected=Expected(receipt_number=wanted.number, lines=_applied(invoices)),
        )


class AmbiguousReceipts(Scenario):
    name = ScenarioName.AMBIGUOUS_RECEIPTS

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, params.lines))
        amount = total([i.amount for i in invoices])
        first = _receipt(tag, params, 1, amount, params.as_of - timedelta(days=1))
        second = _receipt(tag, params, 2, amount, params.as_of + timedelta(days=1))
        no_match = [
            ExpectedLine(
                number=i.number,
                line_status=LineStatus.ALLOCATION_NO_RECEIPT_MATCH,
                applied_amount=_ZERO,
            )
            for i in invoices
        ]
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[first, second],
            remit_lines=_full_lines(invoices),
            payment_amount=amount,
            expected=Expected(
                receipt_number=None, lines=no_match, error_code=ErrorCode.RECEIPT_AMBIGUOUS
            ),
        )


class CreditMemoNetting(Scenario):
    name = ScenarioName.CREDIT_MEMO_NETTING

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, max(params.lines, 2)))
        smallest = min(i.amount for i in invoices)
        memo_amount = to_money(smallest * rng.randint(10, 40) / 100)
        memo = PlannedTransaction(
            number=tagged_number(tag, "CM", 1),
            amount=-memo_amount,
            currency=params.currency,
            transaction_date=params.as_of - _INVOICE_AGE,
        )
        amount = to_money(total([i.amount for i in invoices]) + memo.amount)
        receipt = _receipt(tag, params, 1, amount, params.as_of)
        remit_lines = [
            *_full_lines(invoices),
            RemitLine(memo.number, LineKind.CREDIT_MEMO, gross=memo.amount, paid=memo.amount),
        ]
        expected_lines = [
            ExpectedLine(
                number=memo.number,
                line_status=LineStatus.ALLOCATION_APPLIED,
                applied_amount=memo.amount,
            ),
            *_applied(invoices),
        ]
        return _Draft(
            params=params,
            invoices=invoices,
            credit_memos=[memo],
            receipts=[receipt],
            remit_lines=remit_lines,
            payment_amount=amount,
            expected=Expected(receipt_number=receipt.number, lines=expected_lines),
        )


class AlreadyApplied(Scenario):
    name = ScenarioName.ALREADY_APPLIED

    def build(self, params: ScenarioParams, *, tag: str, customer_account: str) -> _Draft:
        rng = random.Random(params.seed)  # noqa: S311 - deterministic test data, not security
        invoices = _invoices(tag, params, random_amounts(rng, params.lines))
        amount = total([i.amount for i in invoices])
        receipt = _receipt(tag, params, 1, amount, params.as_of)
        applications = [
            PlannedApplication(
                receipt_number=receipt.number, transaction_number=i.number, amount=i.amount
            )
            for i in invoices
        ]
        previously = [
            ExpectedLine(
                number=i.number,
                line_status=LineStatus.ALLOCATION_PREVIOUSLY_APPLIED,
                applied_amount=_ZERO,
            )
            for i in invoices
        ]
        return _Draft(
            params=params,
            invoices=invoices,
            receipts=[receipt],
            remit_lines=_full_lines(invoices),
            payment_amount=amount,
            expected=Expected(receipt_number=receipt.number, lines=previously),
            pre_applications=applications,
        )


PRESETS: Final[Mapping[ScenarioName, Scenario]] = MappingProxyType(
    {
        scenario.name: scenario
        for scenario in (
            OneToOne(),
            SplitPayment(),
            ShortPay(),
            InrRounding(),
            DuplicateAmounts(),
            AmbiguousReceipts(),
            CreditMemoNetting(),
            AlreadyApplied(),
        )
    }
)


def build_plan(
    name: ScenarioName | str, params: ScenarioParams, *, tag: str, customer_account: str
) -> ScenarioPlan:
    """Build the plan for a preset by name; an unknown name raises `ValueError`."""
    return PRESETS[ScenarioName(name)].plan(params, tag=tag, customer_account=customer_account)
