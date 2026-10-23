"""Fusion JSON -> model mapping, shared by every `FusionClient` implementation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import to_money
from cashapp.integrations.fusion import query
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import (
    DiscountTier,
    FusionApplication,
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
    TransactionKind,
)


def as_money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal | str | int) and not isinstance(value, bool):
        return to_money(value)
    raise FusionError(ErrorCode.FUSION_FAULT, "unexpected money value type in Fusion response")


def as_str(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def opt_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise FusionError(
            ErrorCode.FUSION_FAULT, "expected an integer id in Fusion response"
        ) from exc


def as_date(value: Any) -> date:
    if value is None:
        return date.min
    return date.fromisoformat(str(value)[:10])


def opt_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    return date.fromisoformat(str(value)[:10])


def map_payment_terms(row: Mapping[str, Any]) -> PaymentTerms:
    tiers: list[DiscountTier] = []
    raw: Any = row.get(query.PAYMENT_TERMS_TIERS_KEY)
    if isinstance(raw, list):
        for tier in cast("list[Any]", raw):
            if not isinstance(tier, dict):
                continue
            tier_row = cast("dict[str, Any]", tier)
            days: Any = tier_row.get(query.PAYMENT_TERMS_TIER_DAYS)
            percent: Any = tier_row.get(query.PAYMENT_TERMS_TIER_PERCENT)
            if days is None or percent is None:
                continue
            tiers.append(DiscountTier(days=as_int(days), percent=Decimal(str(percent))))
    tiers.sort(key=lambda t: t.days)
    term_id = row.get(query.PAYMENT_TERMS_ID_FIELD)
    return PaymentTerms(
        term_id=None if term_id is None else as_int(term_id),
        name=as_str(row.get(query.PAYMENT_TERMS_NAME_FIELD)),
        discount_tiers=tuple(tiers),
    )


def as_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def map_invoice(row: Mapping[str, Any]) -> FusionTransaction:
    balance = as_money(row.get("InvoiceBalanceAmount"))
    return FusionTransaction(
        customer_trx_id=as_int(row.get("CustomerTransactionId")),
        number=as_str(row.get("TransactionNumber")),
        kind=TransactionKind.INVOICE,
        balance=balance,
        original_amount=as_money(row["EnteredAmount"])
        if row.get("EnteredAmount") is not None
        else balance,
        currency=as_str(row.get("InvoiceCurrencyCode")),
        status=as_str(row.get("InvoiceStatus")),
        bill_to_customer_number=opt_str(row.get("BillToCustomerNumber")),
        bill_to_site=opt_str(row.get("BillToSite")),
        business_unit=opt_str(row.get("BusinessUnit")),
        payment_terms=opt_str(row.get("PaymentTerms")),
        transaction_date=opt_date(row.get("TransactionDate")),  # UNVERIFIED
    )


def map_credit_memo(row: Mapping[str, Any]) -> FusionTransaction:
    balance = -abs(as_money(row.get("TransactionBalanceDue")))
    entered = row.get("EnteredAmount")
    return FusionTransaction(
        customer_trx_id=as_int(row.get("CustomerTransactionId")),
        number=as_str(row.get("TransactionNumber")),
        kind=TransactionKind.CREDIT_MEMO,
        balance=balance,
        original_amount=-abs(as_money(entered)) if entered is not None else balance,
        currency=as_str(row.get("CurrencyCode")),
        status=as_str(row.get("TransactionStatus")),
        bill_to_customer_number=opt_str(row.get("BillToCustomerNumber")),
        bill_to_site=opt_str(row.get("BillToSite")),
        business_unit=opt_str(row.get("BusinessUnit")),
        payment_terms=None,
    )


def map_receipt(row: Mapping[str, Any]) -> FusionReceipt:
    refs_raw = row.get("remittanceReferences")
    refs: list[str] = []
    if isinstance(refs_raw, list):
        for ref in refs_raw:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(ref, dict):
                number = opt_str(ref.get(query.FIELDS_REMITTANCE_REFERENCE))  # pyright: ignore[reportUnknownMemberType]
                if number is not None:
                    refs.append(number)
    return FusionReceipt(
        receipt_id=as_int(row.get("StandardReceiptId")),
        receipt_number=as_str(row.get("ReceiptNumber")),
        amount=as_money(row.get("Amount")),
        unapplied_amount=as_money(row.get("UnappliedAmount")),
        currency=as_str(row.get("Currency")),
        customer_account_number=opt_str(row.get("CustomerAccountNumber")),
        receipt_date=as_date(row.get("ReceiptDate")),
        creation_date=as_datetime(row.get("CreationDate")),
        status=as_str(row.get("Status")),
        state=as_str(row.get("State")),
        remittance_references=tuple(refs),
        comments=opt_str(row.get("Comments")),
    )


def map_application(
    row: Mapping[str, Any], *, receipt_id: int | None = None, customer_trx_id: int | None = None
) -> FusionApplication:
    return FusionApplication(
        application_id=as_int(row.get("ReceivableApplicationId")),
        receipt_id=receipt_id if receipt_id is not None else as_int(row.get("ReceiptId")),
        customer_trx_id=(
            customer_trx_id
            if customer_trx_id is not None
            else as_int(row.get("CustomerTransactionId"))
        ),
        amount_applied=as_money(row.get("AmountApplied")),
        apply_date=as_date(row.get("ApplyDate")),
        status=as_str(row.get("Status"), "APP"),
        discount_amount=(
            as_money(row["DiscountTaken"]) if row.get("DiscountTaken") is not None else None
        ),  # UNVERIFIED: field name
    )
