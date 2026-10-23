"""`McpFusionClient`: the `FusionClient` the stations use.

Reads and REST writes go through the fusion-sql-mcp (Greenlight) server (`McpClient`); the receipt
apply and unapply go direct over SOAP (`SoapTransport`), because the server has no SOAP tool.
Report-style reads are SQL data models run through `run_query` (see `datamodels/`).

Nothing here logs or records a query string, a SQL text or a body. Writes pass the `WriteGuard`
before any I/O.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from datetime import time as dtime
from types import TracebackType
from typing import Any, cast

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion import bip, mappers, query, soap
from cashapp.integrations.fusion.client import ReceiptDateBasis
from cashapp.integrations.fusion.datamodels import (
    CATALOG,
    RELATIONSHIPS_PATH,
    load_sql,
)
from cashapp.integrations.fusion.errors import FusionError, error_from_http
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    AttachmentRef,
    CustomerRelationship,
    FusionApplication,
    FusionCustomer,
    FusionCustomerSite,
    FusionReceipt,
    FusionTransaction,
    PaymentTerms,
    UnapplyRequest,
    UnapplyResult,
)
from cashapp.integrations.mcp.client import McpClient
from cashapp.integrations.mcp.settings import McpConnection
from cashapp.integrations.mcp.sql import render_data_model

__all__ = ["PROBE_VALUES", "McpFusionClient", "McpFusionOptions"]

# Sentinels that cannot exist in a tenant: a correct `in (...)` query returns no rows.
PROBE_VALUES: tuple[str, str] = ("CASHAPP-PREFLIGHT-0", "CASHAPP-PREFLIGHT-1")

_SOURCE_ENV_TTL_S = 60.0

ConnectionFn = Callable[[], Awaitable[McpConnection]]
SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class McpFusionOptions:
    chunk_size: int = 50
    page_size: int = 500
    max_pages: int = 200
    poll_interval_s: float = 1.0
    max_wait_s: float = 120.0


def _url(path: str) -> str:
    return path if path.startswith("/") else f"{query.REST_BASE}/{path}"


def _as_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FusionError(ErrorCode.FUSION_FAULT, "Fusion returned an unexpected JSON shape")
    return cast("dict[str, Any]", value)


class McpFusionClient:
    def __init__(
        self,
        *,
        pod_name: str,
        mcp: McpClient,
        connection: ConnectionFn,
        guard: WriteGuard,
        soap_transport: soap.SoapTransport,
        source: str | None = None,
        options: McpFusionOptions = McpFusionOptions(),  # noqa: B008 - frozen value object
        sleep: SleepFn = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.pod_name = pod_name
        self._mcp = mcp
        self._connection = connection
        self._guard = guard
        self._soap = soap_transport
        self._pod_source = source
        self._options = options
        self._sleep = sleep
        self._monotonic = monotonic
        self._source_env: tuple[str | None, float] | None = None

    @property
    def mcp(self) -> McpClient:
        """The shared MCP client (the preflight lists its tools)."""
        return self._mcp

    async def __aenter__(self) -> McpFusionClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Closes the SOAP transport. The shared MCP client belongs to the process, not to us."""
        await self._soap.aclose()

    # --- MCP plumbing ------------------------------------------------------------------------

    async def _source(self) -> str:
        if self._pod_source:
            return self._pod_source
        conn = await self._connection()
        if not conn.fusion_source:
            raise FusionError(
                ErrorCode.FUSION_FAULT,
                f"no MCP source is configured for pod '{self.pod_name}' "
                "(set the pod's mcp_source or mcp.fusion_source)",
                retryable=False,
            )
        return conn.fusion_source

    async def _rest(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        write: bool = False,
    ) -> tuple[dict[str, Any], bool | None]:
        """One REST tool call -> (body, has_more). A non-2xx status in the reply is an error."""
        data = await self._mcp.call_tool(
            tool, {"source": await self._source(), **args}, write=write
        )
        status = data.get("status")
        if isinstance(status, int) and not 200 <= status < 300:
            error = error_from_http(status, None)
            error.outcome_unknown = write and error.retryable
            raise error
        body = _as_object(data.get("body"))
        has_more = data.get("has_more")
        if not isinstance(has_more, bool):
            raw = body.get("hasMore")
            has_more = raw if isinstance(raw, bool) else None
        return body, has_more

    @staticmethod
    def _rest_params(params: Mapping[str, str] | None, fields: str | None) -> dict[str, str]:
        merged = dict(params or {})
        merged["onlyData"] = "true"
        if fields is not None:
            merged["fields"] = fields
        return merged

    async def _get_json(
        self, path: str, *, params: Mapping[str, str] | None = None, fields: str | None
    ) -> tuple[dict[str, Any], bool | None]:
        return await self._rest(
            "fusion_rest_get", {"path": _url(path), "params": self._rest_params(params, fields)}
        )

    async def _get_paged(
        self,
        path: str,
        *,
        fields: str,
        params: Mapping[str, str] | None = None,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """Follow `has_more`/`offset`, one server call per page. Stops on an empty page."""
        if not fields:
            raise ValueError("fields= is required on every REST read")
        items: list[dict[str, Any]] = []
        offset = 0
        for _ in range(self._options.max_pages):
            page_params = {**(params or {}), "limit": str(self._options.page_size)}
            page_params["offset"] = str(offset)
            body, has_more = await self._get_json(path, params=page_params, fields=fields)
            page = body.get("items", [])
            rows = [_as_object(row) for row in page] if isinstance(page, list) else []  # pyright: ignore[reportUnknownVariableType]
            items.extend(rows)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            if not rows or has_more is not True:
                return items
            offset += len(rows)
        raise FusionError(
            ErrorCode.FUSION_FAULT, f"{path}: exceeded {self._options.max_pages} pages"
        )

    async def verify_framework(self) -> None:
        """Startup check: an `in (...)` probe must not 400 (REST-Framework-Version 4 is required).

        A 400 raises a clear `FUSION_FAULT`. A transport or auth failure propagates unchanged so the
        caller can decide whether to continue.
        """
        try:
            await self._get_json(
                "receivablesInvoices",
                params={"q": query.q_in("TransactionNumber", PROBE_VALUES), "limit": "1"},
                fields="CustomerTransactionId",
            )
        except FusionError as exc:
            if exc.http_status == 400:
                raise FusionError(
                    ErrorCode.FUSION_FAULT,
                    "the Fusion REST probe `in (...)` returned 400: the MCP server is not "
                    "sending REST-Framework-Version 4 (check fusion_rest_framework_version)",
                    retryable=False,
                    http_status=400,
                ) from exc
            raise

    # --- reads -------------------------------------------------------------------------------

    async def find_transactions(self, numbers: Sequence[str]) -> list[FusionTransaction]:
        found: list[FusionTransaction] = []
        for chunk in query.chunked(numbers, self._options.chunk_size):
            q = query.q_in("TransactionNumber", chunk)
            invoices, memos = await asyncio.gather(
                self._get_paged(
                    "receivablesInvoices", fields=query.FIELDS_INVOICE, params={"q": q}
                ),
                self._get_paged(
                    "receivablesCreditMemos", fields=query.FIELDS_CREDIT_MEMO, params={"q": q}
                ),
            )
            found.extend(mappers.map_invoice(row) for row in invoices)
            found.extend(mappers.map_credit_memo(row) for row in memos)
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
                start = datetime.combine(date_from, dtime.min, tzinfo=UTC)
                end = datetime.combine(date_to, dtime(23, 59, 59), tzinfo=UTC)
                window = (
                    f"CreationDate BETWEEN {query.q_datetime(start)} AND {query.q_datetime(end)}"
                )
            rows = await self._get_paged(
                "standardReceipts",
                fields=query.FIELDS_RECEIPT,
                params={
                    "q": f"{query.q_in('CustomerAccountNumber', chunk)} AND {window}",
                    "expand": "remittanceReferences",
                },
            )
            for row in rows:
                receipt = mappers.map_receipt(row)
                receipts[receipt.receipt_id] = receipt
        return list(receipts.values())

    async def receipts_created_since(
        self, since: datetime, *, limit: int = 500
    ) -> list[FusionReceipt]:
        rows = await self._get_paged(
            "standardReceipts",
            fields=query.FIELDS_RECEIPT,
            params={
                "q": f"CreationDate >= {query.q_datetime(since)}",
                "orderBy": "CreationDate:asc,StandardReceiptId:asc",
                "expand": "remittanceReferences",
            },
            max_items=limit,
        )
        return [mappers.map_receipt(row) for row in rows]

    async def get_receipt(self, receipt_id: int) -> FusionReceipt:
        body, _ = await self._get_json(
            f"standardReceipts/{int(receipt_id)}",
            params={"expand": "remittanceReferences"},
            fields=query.FIELDS_RECEIPT,
        )
        return mappers.map_receipt(body)

    async def list_receipt_applications(self, receipt_id: int) -> list[FusionApplication]:
        # UNVERIFIED: child resource name; falls back to a data model if absent (s32).
        rows = await self._get_paged(
            f"standardReceipts/{int(receipt_id)}/child/receiptApplications",
            fields=query.FIELDS_RECEIPT_APPLICATION,
        )
        return [mappers.map_application(row, receipt_id=receipt_id) for row in rows]

    async def list_transaction_applications(self, customer_trx_id: int) -> list[FusionApplication]:
        # UNVERIFIED: child resource name; falls back to a data model if absent (s32).
        rows = await self._get_paged(
            f"receivablesInvoices/{int(customer_trx_id)}/child/receiptApplications",
            fields=query.FIELDS_RECEIPT_APPLICATION + ",ReceiptId",
        )
        return [mappers.map_application(row, customer_trx_id=customer_trx_id) for row in rows]

    async def list_receipt_attachments(self, receipt_id: int) -> list[AttachmentRef]:
        # UNVERIFIED (s17): child resource name and fields (describe lists them; no read probe yet).
        rows = await self._get_paged(
            f"standardReceipts/{int(receipt_id)}/child/attachments",
            fields=query.FIELDS_ATTACHMENTS,
        )
        return [
            AttachmentRef(
                receipt_id=receipt_id,
                attachment_id=mappers.opt_str(row.get("AttachedDocumentId")),
                filename=mappers.as_str(row.get("FileName")),
                title=mappers.opt_str(row.get("Title")),
            )
            for row in rows
        ]

    async def get_customer_account(self, account_number: str) -> FusionCustomer:
        # UNVERIFIED: resource, filter and every field name.
        rows = await self._get_paged(
            query.CUSTOMER_ACCOUNTS_PATH,
            fields=query.FIELDS_CUSTOMER_ACCOUNT,
            params={"q": f"AccountNumber={query.q_literal(account_number)}"},
        )
        rows = [r for r in rows if mappers.opt_str(r.get("AccountNumber")) == account_number]
        if not rows:
            raise FusionError(
                ErrorCode.CUSTOMER_NOT_FOUND, "customer account not found", retryable=False
            )
        currencies: list[str] = []
        sites: dict[str, FusionCustomerSite] = {}
        for row in rows:
            currency = mappers.opt_str(row.get("Currency"))
            if currency is not None and currency not in currencies:
                currencies.append(currency)
            site_number = mappers.opt_str(row.get("SiteNumber"))
            if site_number is not None:
                sites[site_number] = FusionCustomerSite(
                    site_number=site_number,
                    purpose=mappers.opt_str(row.get("SitePurpose")),
                    location=mappers.opt_str(row.get("Location")),
                    address=mappers.opt_str(row.get("Address")),
                )
        return FusionCustomer(
            account_number=account_number,
            name=mappers.as_str(rows[0].get("PartyName")),
            currency_codes=tuple(currencies),
            sites=tuple(sites.values()),
        )

    async def get_payment_terms(self, term: int | str) -> PaymentTerms | None:
        # UNVERIFIED: resource, filter and every field name (CONTRACTS.md, s39 live probe).
        if isinstance(term, int):
            flt = f"{query.PAYMENT_TERMS_ID_FIELD}={int(term)}"
        else:
            flt = f"{query.PAYMENT_TERMS_NAME_FIELD}={query.q_literal(term)}"
        rows = await self._get_paged(
            query.PAYMENT_TERMS_RESOURCE, fields=query.FIELDS_PAYMENT_TERMS, params={"q": flt}
        )
        if not rows:
            return None
        return mappers.map_payment_terms(rows[0])

    async def customer_relationships(
        self, account_numbers: Sequence[str]
    ) -> list[CustomerRelationship]:
        found: list[CustomerRelationship] = []
        for chunk in query.chunked(account_numbers, self._options.chunk_size):
            data = await self.run_report(
                RELATIONSHIPS_PATH, {bip.RELATIONSHIPS_PARAM: ",".join(chunk)}
            )
            found.extend(bip.parse_relationships_xml(data))
        return found

    async def run_report(self, path: str, params: Mapping[str, str], fmt: str = "xml") -> bytes:
        """Run a catalog data model as ad-hoc SQL and return it as `DATA_DS/G_1` XML."""
        if fmt != "xml":
            raise FusionError(
                ErrorCode.FUSION_FAULT, "only xml output is available over MCP", retryable=False
            )
        model = CATALOG.get(path)
        if model is None:
            raise FusionError(
                ErrorCode.FUSION_FAULT, f"'{path}' is not a known data model", retryable=False
            )
        sql = render_data_model(load_sql(path), params, model.binds)
        conn = await self._connection()
        out = await self._mcp.call_tool(
            "run_query",
            {
                "source": await self._source(),
                "sql": sql,
                "max_rows": conn.max_rows,
                "keep_result": True,
            },
        )
        columns, rows = await self._collect_rows(out, conn)
        return bip.rows_to_data_ds_xml(columns, rows)

    async def _collect_rows(
        self, out: dict[str, Any], conn: McpConnection
    ) -> tuple[list[str], list[list[Any]]]:
        """Wait for a kept result to be ready, then read every row (never a silent partial)."""
        deadline = self._monotonic() + self._options.max_wait_s
        while out.get("status") == "running":
            result_id = out.get("result_id")
            if not isinstance(result_id, str) or self._monotonic() >= deadline:
                raise FusionError(
                    ErrorCode.FUSION_TRANSIENT, "the Fusion query did not finish in time"
                )
            await self._sleep(self._options.poll_interval_s)
            out = await self._mcp.call_tool(
                "fetch_rows", {"result_id": result_id, "offset": 0, "max_rows": conn.max_rows}
            )
        if out.get("status") == "failed":
            raise FusionError(ErrorCode.FUSION_FAULT, "the Fusion query failed", retryable=False)
        columns = [str(c) for c in cast("list[Any]", out.get("columns", []))]
        rows = [list(r) for r in cast("list[Any]", out.get("rows", []))]
        result_id = out.get("result_id")
        while out.get("truncated") is True:
            if not isinstance(result_id, str):
                raise FusionError(
                    ErrorCode.FUSION_FAULT, "the Fusion query result was cut short", retryable=False
                )
            out = await self._mcp.call_tool(
                "fetch_rows",
                {"result_id": result_id, "offset": len(rows), "max_rows": conn.max_rows},
            )
            page = [list(r) for r in cast("list[Any]", out.get("rows", []))]
            if not page:
                break
            rows.extend(page)
        return columns, rows

    async def rest_get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        merged = dict(params or {})
        fields = merged.pop("fields", None)
        body, _ = await self._get_json(path, params=merged, fields=fields)
        return body

    async def get_raw(self, path: str, params: Mapping[str, str] | None = None) -> bytes:
        """Only a SOAP `?WSDL` is served (direct); the MCP server has no binary GET."""
        bare, _, tail = path.partition("?")
        if tail.upper() == "WSDL" and bare.startswith("/fscmService/"):
            return await self._soap.get_wsdl(bare)
        raise FusionError(
            ErrorCode.FUSION_FAULT, "binary downloads are not available over MCP", retryable=False
        )

    # --- writes ------------------------------------------------------------------------------

    async def _assert_writable(self, method: str) -> None:
        """The write rails: config flag, production pod, then what the MCP source says it is."""
        self._guard.check(method)
        source = await self._source()
        now = self._monotonic()
        cached = self._source_env
        if cached is None or cached[1] <= now:
            data = await self._mcp.call_tool("list_sources", {})
            environment: str | None = None
            for entry in cast("list[Any]", data.get("result", [])):
                if isinstance(entry, dict) and entry.get("name") == source:  # pyright: ignore[reportUnknownMemberType]
                    raw = entry.get("environment")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                    environment = raw if isinstance(raw, str) else None
            cached = (environment, now + _SOURCE_ENV_TTL_S)
            self._source_env = cached
        self._guard.check_source(method, cached[0])

    async def apply_receipt(self, request: ApplyRequest) -> ApplyResult:
        await self._assert_writable("apply_receipt")
        raw = await self._soap.post_soap(
            soap.SOAP_PATH_RECEIPTS,
            soap.build_apply_envelope(request),
            action=soap.SOAP_ACTION_APPLY,
            op="apply_receipt",
            write=True,
        )
        return soap.parse_apply_response(raw, receipt_id=request.receipt_id)

    async def unapply_receipt(self, request: UnapplyRequest) -> UnapplyResult:
        await self._assert_writable("unapply_receipt")
        raw = await self._soap.post_soap(
            soap.SOAP_PATH_RECEIPTS,
            soap.build_unapply_envelope(request),
            action=soap.SOAP_ACTION_UNAPPLY,
            op="unapply_receipt",
            write=True,
        )
        return soap.parse_unapply_response(raw)

    async def _rest_write(
        self, method: str, http_method: str, path: str, body: Mapping[str, Any]
    ) -> dict[str, Any]:
        await self._assert_writable(method)
        result, _ = await self._rest(
            "fusion_rest_write",
            {"method": http_method, "path": _url(path), "body": dict(body)},
            write=True,
        )
        return result

    async def set_receipt_comment(self, receipt_id: int, text: str) -> None:
        # UNVERIFIED (s17): the Comments field and its size limit.
        await self._rest_write(
            "set_receipt_comment",
            "PATCH",
            f"standardReceipts/{int(receipt_id)}",
            {"Comments": text},
        )

    async def attach_to_receipt(
        self, receipt_id: int, filename: str, content: bytes, content_type: str, title: str
    ) -> AttachmentRef:
        # UNVERIFIED (s17): child resource and body fields.
        body = await self._rest_write(
            "attach_to_receipt",
            "POST",
            f"standardReceipts/{int(receipt_id)}/child/attachments",
            {
                "DatatypeCode": "FILE",
                "FileName": filename,
                "Title": title,
                "UploadedFileContentType": content_type,
                "FileContents": base64.b64encode(content).decode("ascii"),
            },
        )
        return AttachmentRef(
            receipt_id=receipt_id,
            attachment_id=mappers.opt_str(body.get("AttachedDocumentId")),
            filename=filename,
            title=title,
        )

    async def rest_post(self, path: str, json: Mapping[str, Any]) -> dict[str, Any]:
        return await self._rest_write("rest_post", "POST", path, json)
