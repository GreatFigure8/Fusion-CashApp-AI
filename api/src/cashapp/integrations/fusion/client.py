"""`FusionClient`: the one interface every station uses to talk to Fusion.

`HttpFusionClient` is the real implementation (REST + SOAP + BI Publisher). Names marked
UNVERIFIED are tracked in CONTRACTS.md and confirmed by the `-m live` probes.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import TracebackType
from typing import Any, Literal, Protocol, cast

import httpx

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import to_money
from cashapp.integrations.fusion import bip, query, soap
from cashapp.integrations.fusion.errors import FusionError
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
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
    TransactionKind,
    UnapplyRequest,
    UnapplyResult,
)
from cashapp.integrations.fusion.transport import FusionClientOptions, FusionTransport
from cashapp.settings import FusionPodSettings

__all__ = ["FusionClient", "FusionClientOptions", "HttpFusionClient", "ReceiptDateBasis"]

ReceiptDateBasis = Literal["receipt_date", "creation_date"]


class FusionClient(Protocol):
    pod_name: str

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]: ...

    async def find_receipts(
        self,
        *,
        customer_numbers: Sequence[str],
        date_from: date,
        date_to: date,
        by: ReceiptDateBasis = "receipt_date",
    ) -> list[FusionReceipt]: ...

    async def receipts_created_since(
        self, since: datetime, *, limit: int = 500
    ) -> list[FusionReceipt]: ...

    async def get_receipt(self, receipt_id: int) -> FusionReceipt: ...

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]: ...

    async def list_transaction_applications(
        self, customer_trx_id: int
    ) -> list[FusionApplication]: ...

    async def get_customer_account(self, account_number: str) -> FusionCustomer: ...

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None: ...

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]: ...

    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult: ...

    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult: ...

    async def set_receipt_comment(self, receipt_id: int, text: str) -> None: ...

    async def attach_to_receipt(
        self, receipt_id: int, filename: str, content: bytes, content_type: str, title: str
    ) -> AttachmentRef: ...

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes: ...

    async def rest_get(
        self, path: str, params: Mapping[str, str] | None = None
    ) -> dict[str, Any]: ...

    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes: ...

    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


# --- JSON -> model mapping ----------------------------------------------------------------


def _money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal | str | int) and not isinstance(value, bool):
        return to_money(value)
    raise FusionError(ErrorCode.FUSION_FAULT, "unexpected money value type in Fusion response")


def _str(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise FusionError(
            ErrorCode.FUSION_FAULT, "expected an integer id in Fusion response"
        ) from exc


def _date(value: Any) -> date:
    if value is None:
        return date.min
    return date.fromisoformat(str(value)[:10])


def _opt_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    return date.fromisoformat(str(value)[:10])


def _map_payment_terms(row: Mapping[str, Any]) -> PaymentTerms:
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
            tiers.append(DiscountTier(days=_int(days), percent=Decimal(str(percent))))
    tiers.sort(key=lambda t: t.days)
    term_id = row.get(query.PAYMENT_TERMS_ID_FIELD)
    return PaymentTerms(
        term_id=None if term_id is None else _int(term_id),
        name=_str(row.get(query.PAYMENT_TERMS_NAME_FIELD)),
        discount_tiers=tuple(tiers),
    )


def _datetime(value: Any) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _map_invoice(row: Mapping[str, Any]) -> FusionTransaction:
    balance = _money(row.get("InvoiceBalanceAmount"))
    return FusionTransaction(
        customer_trx_id=_int(row.get("CustomerTransactionId")),
        number=_str(row.get("TransactionNumber")),
        kind=TransactionKind.INVOICE,
        balance=balance,
        original_amount=_money(row["EnteredAmount"])
        if row.get("EnteredAmount") is not None
        else balance,
        currency=_str(row.get("InvoiceCurrencyCode")),
        status=_str(row.get("InvoiceStatus")),
        bill_to_customer_number=_opt_str(row.get("BillToCustomerNumber")),
        bill_to_site=_opt_str(row.get("BillToSite")),
        business_unit=_opt_str(row.get("BusinessUnit")),
        payment_terms=_opt_str(row.get("PaymentTerms")),
        transaction_date=_opt_date(row.get("TransactionDate")),  # UNVERIFIED
    )


def _map_credit_memo(row: Mapping[str, Any]) -> FusionTransaction:
    balance = -abs(_money(row.get("TransactionBalanceDue")))
    entered = row.get("EnteredAmount")
    return FusionTransaction(
        customer_trx_id=_int(row.get("CustomerTransactionId")),
        number=_str(row.get("TransactionNumber")),
        kind=TransactionKind.CREDIT_MEMO,
        balance=balance,
        original_amount=-abs(_money(entered)) if entered is not None else balance,
        currency=_str(row.get("CurrencyCode")),
        status=_str(row.get("TransactionStatus")),
        bill_to_customer_number=_opt_str(row.get("BillToCustomerNumber")),
        bill_to_site=_opt_str(row.get("BillToSite")),
        business_unit=_opt_str(row.get("BusinessUnit")),
        payment_terms=None,
    )


def _map_receipt(row: Mapping[str, Any]) -> FusionReceipt:
    refs_raw = row.get("remittanceReferences")
    refs: list[str] = []
    if isinstance(refs_raw, list):
        for ref in refs_raw:  # pyright: ignore[reportUnknownVariableType]
            if isinstance(ref, dict):
                number = _opt_str(ref.get(query.FIELDS_REMITTANCE_REFERENCE))  # pyright: ignore[reportUnknownMemberType]
                if number is not None:
                    refs.append(number)
    return FusionReceipt(
        receipt_id=_int(row.get("StandardReceiptId")),
        receipt_number=_str(row.get("ReceiptNumber")),
        amount=_money(row.get("Amount")),
        unapplied_amount=_money(row.get("UnappliedAmount")),
        currency=_str(row.get("Currency")),
        customer_account_number=_opt_str(row.get("CustomerAccountNumber")),
        receipt_date=_date(row.get("ReceiptDate")),
        creation_date=_datetime(row.get("CreationDate")),
        status=_str(row.get("Status")),
        state=_str(row.get("State")),
        remittance_references=tuple(refs),
        comments=_opt_str(row.get("Comments")),
    )


def _map_application(
    row: Mapping[str, Any], *, receipt_id: int | None = None, customer_trx_id: int | None = None
) -> FusionApplication:
    return FusionApplication(
        application_id=_int(row.get("ReceivableApplicationId")),
        receipt_id=receipt_id if receipt_id is not None else _int(row.get("ReceiptId")),
        customer_trx_id=(
            customer_trx_id
            if customer_trx_id is not None
            else _int(row.get("CustomerTransactionId"))
        ),
        amount_applied=_money(row.get("AmountApplied")),
        apply_date=_date(row.get("ApplyDate")),
        status=_str(row.get("Status"), "APP"),
        discount_amount=(
            _money(row["DiscountTaken"]) if row.get("DiscountTaken") is not None else None
        ),  # UNVERIFIED: field name
    )


class HttpFusionClient:
    def __init__(
        self,
        *,
        pod_name: str,
        pod: FusionPodSettings,
        guard: WriteGuard,
        relationships_report_path: str,
        options: FusionClientOptions = FusionClientOptions(),  # noqa: B008 - frozen value object
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.pod_name = pod_name
        self._guard = guard
        self._relationships_report_path = relationships_report_path
        self._options = options
        self._http = FusionTransport(
            pod_name=pod_name, pod=pod, options=options, transport=transport, sleep=sleep
        )

    async def __aenter__(self) -> HttpFusionClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _url(path: str) -> str:
        return path if path.startswith("/") else f"{query.REST_BASE}/{path}"

    # --- reads -----------------------------------------------------------------------------

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]:
        found: list[FusionTransaction] = []
        for chunk in query.chunked(numbers, self._options.chunk_size):
            q = query.q_in("TransactionNumber", chunk)
            invoices, memos = await asyncio.gather(
                self._http.get_json_paged(
                    self._url("receivablesInvoices"),
                    op="find_invoices",
                    fields=query.FIELDS_INVOICE,
                    params={"q": q},
                ),
                self._http.get_json_paged(
                    self._url("receivablesCreditMemos"),
                    op="find_credit_memos",
                    fields=query.FIELDS_CREDIT_MEMO,
                    params={"q": q},
                ),
            )
            found.extend(_map_invoice(row) for row in invoices)
            found.extend(_map_credit_memo(row) for row in memos)
        return found

    async def find_receipts(
        self,
        *,
        customer_numbers: Sequence[str],
        date_from: date,
        date_to: date,
        by: ReceiptDateBasis = "receipt_date",
    ) -> list[FusionReceipt]:
        receipts: dict[int, FusionReceipt] = {}
        for chunk in query.chunked(customer_numbers, self._options.chunk_size):
            if by == "receipt_date":
                window = (
                    f"ReceiptDate BETWEEN {query.q_date(date_from)} AND {query.q_date(date_to)}"
                )
            else:
                start = datetime.combine(date_from, time.min, tzinfo=UTC)
                end = datetime.combine(date_to, time(23, 59, 59), tzinfo=UTC)
                window = (
                    f"CreationDate BETWEEN {query.q_datetime(start)} AND {query.q_datetime(end)}"
                )
            rows = await self._http.get_json_paged(
                self._url("standardReceipts"),
                op="find_receipts",
                fields=query.FIELDS_RECEIPT,
                params={
                    "q": f"{query.q_in('CustomerAccountNumber', chunk)} AND {window}",
                    "expand": "remittanceReferences",
                },
            )
            for row in rows:
                receipt = _map_receipt(row)
                receipts[receipt.receipt_id] = receipt
        return list(receipts.values())

    async def receipts_created_since(
        self, since: datetime, *, limit: int = 500
    ) -> list[FusionReceipt]:
        rows = await self._http.get_json_paged(
            self._url("standardReceipts"),
            op="receipts_created_since",
            fields=query.FIELDS_RECEIPT,
            params={
                "q": f"CreationDate >= {query.q_datetime(since)}",
                "orderBy": "CreationDate:asc,StandardReceiptId:asc",
                "expand": "remittanceReferences",
            },
            max_items=limit,
        )
        return [_map_receipt(row) for row in rows]

    async def get_receipt(self, receipt_id: int) -> FusionReceipt:
        row = await self._http.get_json(
            self._url(f"standardReceipts/{int(receipt_id)}"),
            op="get_receipt",
            params={"expand": "remittanceReferences"},
            fields=query.FIELDS_RECEIPT,
        )
        return _map_receipt(row)

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]:
        # UNVERIFIED: child resource name; falls back to a BIP data model if absent (s32).
        rows = await self._http.get_json_paged(
            self._url(f"standardReceipts/{int(receipt_id)}/child/receiptApplications"),
            op="list_receipt_applications",
            fields=query.FIELDS_RECEIPT_APPLICATION,
        )
        return [_map_application(row, receipt_id=receipt_id) for row in rows]

    async def list_transaction_applications(self, customer_trx_id: int) -> list[FusionApplication]:
        # UNVERIFIED: child resource name; falls back to a BIP data model if absent (s32).
        rows = await self._http.get_json_paged(
            self._url(f"receivablesInvoices/{int(customer_trx_id)}/child/receiptApplications"),
            op="list_transaction_applications",
            fields=query.FIELDS_RECEIPT_APPLICATION + ",ReceiptId",
        )
        return [_map_application(row, customer_trx_id=customer_trx_id) for row in rows]

    async def get_customer_account(self, account_number: str) -> FusionCustomer:
        # UNVERIFIED: resource, filter and every field name.
        rows = await self._http.get_json_paged(
            query.CUSTOMER_ACCOUNTS_PATH,
            op="get_customer_account",
            fields=query.FIELDS_CUSTOMER_ACCOUNT,
            params={"q": f"AccountNumber={query.q_literal(account_number)}"},
        )
        rows = [r for r in rows if _opt_str(r.get("AccountNumber")) == account_number]
        if not rows:
            raise FusionError(
                ErrorCode.CUSTOMER_NOT_FOUND, "customer account not found", retryable=False
            )
        currencies: list[str] = []
        sites: dict[str, FusionCustomerSite] = {}
        for row in rows:
            currency = _opt_str(row.get("Currency"))
            if currency is not None and currency not in currencies:
                currencies.append(currency)
            site_number = _opt_str(row.get("SiteNumber"))
            if site_number is not None:
                sites[site_number] = FusionCustomerSite(
                    site_number=site_number,
                    purpose=_opt_str(row.get("SitePurpose")),
                    location=_opt_str(row.get("Location")),
                    address=_opt_str(row.get("Address")),
                )
        return FusionCustomer(
            account_number=account_number,
            name=_str(rows[0].get("PartyName")),
            currency_codes=tuple(currencies),
            sites=tuple(sites.values()),
        )

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None:
        # UNVERIFIED: resource, filter and every field name (CONTRACTS.md, s39 live probe).
        if isinstance(term, int):
            rows = await self._http.get_json_paged(
                self._url(query.PAYMENT_TERMS_RESOURCE),
                op="get_payment_terms",
                fields=query.FIELDS_PAYMENT_TERMS,
                params={"q": f"{query.PAYMENT_TERMS_ID_FIELD}={int(term)}"},
            )
        else:
            rows = await self._http.get_json_paged(
                self._url(query.PAYMENT_TERMS_RESOURCE),
                op="get_payment_terms",
                fields=query.FIELDS_PAYMENT_TERMS,
                params={"q": f"{query.PAYMENT_TERMS_NAME_FIELD}={query.q_literal(term)}"},
            )
        if not rows:
            return None
        return _map_payment_terms(rows[0])

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]:
        found: list[CustomerRelationship] = []
        for chunk in query.chunked(account_numbers, self._options.chunk_size):
            data = await self.run_report(
                self._relationships_report_path, {bip.RELATIONSHIPS_PARAM: ",".join(chunk)}
            )
            found.extend(bip.parse_relationships_xml(data))
        return found

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes:
        envelope = bip.build_run_report_envelope(path, params, fmt)
        raw = await self._http.post_soap(
            bip.BIP_PATH, envelope, action="runReport", op="run_report", write=False
        )
        return bip.parse_run_report_response(raw)

    async def rest_get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        merged = dict(params or {})
        fields = merged.pop("fields", None)
        return await self._http.get_json(
            self._url(path), op="rest_get", params=merged, fields=fields
        )

    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes:
        """Plain GET (read retry policy) returning the body bytes, e.g. a SOAP `?WSDL`."""
        return await self._http.get_bytes(self._url(path), op="get_raw", params=params)

    # --- writes ----------------------------------------------------------------------------

    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult:
        self._guard.check("apply_receipt")
        raw = await self._http.post_soap(
            soap.SOAP_PATH_RECEIPTS,
            soap.build_apply_envelope(request),
            action=soap.SOAP_ACTION_APPLY,
            op="apply_receipt",
            write=True,
        )
        return soap.parse_apply_response(raw, receipt_id=request.receipt_id)

    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult:
        self._guard.check("unapply_receipt")
        raw = await self._http.post_soap(
            soap.SOAP_PATH_RECEIPTS,
            soap.build_unapply_envelope(request),
            action=soap.SOAP_ACTION_UNAPPLY,
            op="unapply_receipt",
            write=True,
        )
        return soap.parse_unapply_response(raw)

    async def set_receipt_comment(self, receipt_id: int, text: str) -> None:
        self._guard.check("set_receipt_comment")
        # UNVERIFIED (s17): the Comments field and its size limit.
        await self._http.send_json(
            "PATCH",
            self._url(f"standardReceipts/{int(receipt_id)}"),
            {"Comments": text},
            op="set_receipt_comment",
        )

    async def attach_to_receipt(
        self, receipt_id: int, filename: str, content: bytes, content_type: str, title: str
    ) -> AttachmentRef:
        self._guard.check("attach_to_receipt")
        # UNVERIFIED (s17): child resource and body fields.
        body = await self._http.send_json(
            "POST",
            self._url(f"standardReceipts/{int(receipt_id)}/child/attachments"),
            {
                "DatatypeCode": "FILE",
                "FileName": filename,
                "Title": title,
                "UploadedFileContentType": content_type,
                "FileContents": base64.b64encode(content).decode("ascii"),
            },
            op="attach_to_receipt",
        )
        return AttachmentRef(
            receipt_id=receipt_id,
            attachment_id=_opt_str(body.get("AttachedDocumentId")),
            filename=filename,
        )

    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]:
        self._guard.check("rest_post")
        return await self._http.send_json("POST", self._url(path), json, op="rest_post")
