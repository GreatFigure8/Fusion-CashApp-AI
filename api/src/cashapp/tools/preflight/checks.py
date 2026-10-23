"""The preflight check list. Read-only: only `rest_get`, `get_raw` and `run_report` are called.

Each check is isolated: a failure becomes a FAIL row and the rest still run. Failure text holds
only the error code, HTTP status and Fusion code, never a body, query string or credential.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cashapp.integrations.fusion import bip, query, soap
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    first_local,
    iter_local,
    local_name,
    safe_fromstring,
)
from cashapp.settings import Settings
from cashapp.tools.preflight.report import CheckResult, CheckStatus, PreflightReport

__all__ = ["CHECK_NAMES", "PROBE_VALUES", "PreflightContext", "run_preflight"]

# Sentinels that cannot exist in a tenant: a correct `in (...)` query returns no rows.
PROBE_VALUES: tuple[str, str] = ("CASHAPP-PREFLIGHT-0", "CASHAPP-PREFLIGHT-1")

CHECK_NAMES: tuple[str, ...] = (
    "auth",
    "rest.receivablesInvoices",
    "rest.receivablesCreditMemos",
    "rest.standardReceipts",
    "rest.customerAccounts",
    "rest.pagination",
    "soap.StandardReceiptService.wsdl",
    "bip.ExternalReportWSSService.wsdl",
    "bip.relationships_report",
    "rest.attachments",
    "config.write_enabled",
    "config.pod_is_production",
)

_ATTACHMENTS_CHILD = "attachments"


@dataclass(frozen=True, slots=True)
class PreflightContext:
    pod_name: str
    env: str
    is_production: bool
    write_enabled: bool
    relationships_report_path: str
    check_timeout_s: float = 30.0

    @classmethod
    def from_settings(
        cls, settings: Settings, pod_name: str, *, check_timeout_s: float = 30.0
    ) -> PreflightContext:
        pod = settings.fusion.pods[pod_name]
        return cls(
            pod_name=pod_name,
            env=str(settings.env),
            is_production=pod.is_production,
            write_enabled=settings.fusion.write_enabled,
            relationships_report_path=settings.fusion.relationships_report_path,
            check_timeout_s=check_timeout_s,
        )


class _CheckFailedError(Exception):
    """A check's own verdict; the message is safe to print."""


Outcome = tuple[CheckStatus, str]
Check = Callable[[FusionClient, PreflightContext], Awaitable[Outcome]]


def _items(body: dict[str, Any]) -> list[Any]:
    items = body.get("items")
    if not isinstance(items, list):
        raise _CheckFailedError("response has no items list")
    return items  # pyright: ignore[reportUnknownVariableType]


async def _auth(client: FusionClient, _ctx: PreflightContext) -> Outcome:
    body = await client.rest_get(
        "receivablesInvoices", {"limit": "1", "fields": "CustomerTransactionId"}
    )
    _items(body)
    return CheckStatus.PASS, "authenticated"


def _empty_in_probe(path: str, field: str, fields: str, *, expand: str | None = None) -> Check:
    async def check(client: FusionClient, _ctx: PreflightContext) -> Outcome:
        params = {"q": query.q_in(field, PROBE_VALUES), "fields": fields, "limit": "1"}
        if expand is not None:
            params["expand"] = expand
        body = await client.rest_get(path, params)
        if _items(body):
            raise _CheckFailedError("probe returned rows for sentinel values")
        return CheckStatus.PASS, "in (...) accepted with REST-Framework-Version 4"

    return check


async def _pagination(client: FusionClient, _ctx: PreflightContext) -> Outcome:
    first = await client.rest_get(
        "standardReceipts", {"limit": "1", "offset": "0", "fields": "StandardReceiptId"}
    )
    rows = _items(first)
    has_more = first.get("hasMore")
    if not isinstance(has_more, bool):
        raise _CheckFailedError("hasMore is not a boolean")
    if not has_more:
        return CheckStatus.PASS, "single page on pod"
    second = await client.rest_get(
        "standardReceipts", {"limit": "1", "offset": "1", "fields": "StandardReceiptId"}
    )
    more = _items(second)
    if not more or not rows:
        raise _CheckFailedError("hasMore is true but the next page is empty")
    if more[0] == rows[0]:
        raise _CheckFailedError("offset did not advance the page")
    return CheckStatus.PASS, "hasMore and offset paging work"


def _wsdl_operations(data: bytes) -> set[str]:
    try:
        root = safe_fromstring(data)
    except XmlParseError as exc:
        raise _CheckFailedError("WSDL is not well-formed XML") from exc
    if local_name(root.tag) != "definitions":
        raise _CheckFailedError("document is not a WSDL")
    return {name for op in iter_local(root, "operation") if (name := op.get("name")) is not None}


def _wsdl_check(path: str, operation: str) -> Check:
    async def check(client: FusionClient, _ctx: PreflightContext) -> Outcome:
        operations = _wsdl_operations(await client.get_raw(f"{path}?WSDL"))
        if operation not in operations:
            raise _CheckFailedError(f"operation {operation} not in WSDL")
        return CheckStatus.PASS, f"WSDL reachable, {operation} present"

    return check


async def _relationships_report(client: FusionClient, ctx: PreflightContext) -> Outcome:
    data = await client.run_report(
        ctx.relationships_report_path, {bip.RELATIONSHIPS_PARAM: PROBE_VALUES[0]}, "xml"
    )
    try:
        root = safe_fromstring(data)
    except XmlParseError as exc:
        raise _CheckFailedError("report did not return well-formed XML") from exc
    if local_name(root.tag) != "DATA_DS":
        raise _CheckFailedError("report root is not DATA_DS")
    if first_local(root, "G_1") is not None:
        raise _CheckFailedError("report returned rows for a known-empty parameter")
    return CheckStatus.PASS, "report present, XML, empty for sentinel account"


def _has_child(node: Any, name: str) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():  # pyright: ignore[reportUnknownVariableType]
            if str(key).lower() == name or _has_child(value, name):  # pyright: ignore[reportUnknownArgumentType]
                return True
    elif isinstance(node, list):
        return any(_has_child(value, name) for value in node)  # pyright: ignore[reportUnknownVariableType]
    return False


async def _attachments(client: FusionClient, _ctx: PreflightContext) -> Outcome:
    # UNVERIFIED: describe path and the shape that lists child resources (CONTRACTS.md).
    described = await client.rest_get("standardReceipts/describe")
    if not _has_child(described, _ATTACHMENTS_CHILD):
        raise _CheckFailedError("standardReceipts has no attachments child resource")
    return CheckStatus.PASS, "attachments child resource describable"


async def _write_enabled(_client: FusionClient, ctx: PreflightContext) -> Outcome:
    return CheckStatus.INFO, str(ctx.write_enabled).lower()


async def _pod_is_production(_client: FusionClient, ctx: PreflightContext) -> Outcome:
    return CheckStatus.INFO, f"{str(ctx.is_production).lower()} env={ctx.env}"


def _checks() -> tuple[tuple[str, Check], ...]:
    steps: tuple[Check, ...] = (
        _auth,
        _empty_in_probe("receivablesInvoices", "TransactionNumber", "CustomerTransactionId"),
        _empty_in_probe("receivablesCreditMemos", "TransactionNumber", "CustomerTransactionId"),
        _empty_in_probe(
            "standardReceipts", "ReceiptNumber", "StandardReceiptId", expand="remittanceReferences"
        ),
        _empty_in_probe(query.CUSTOMER_ACCOUNTS_PATH, "AccountNumber", "AccountNumber"),
        _pagination,
        _wsdl_check(soap.SOAP_PATH_RECEIPTS, "createApplyReceipt"),
        _wsdl_check(bip.BIP_PATH, "runReport"),
        _relationships_report,
        _attachments,
        _write_enabled,
        _pod_is_production,
    )
    return tuple(zip(CHECK_NAMES, steps, strict=True))


def _failure_detail(exc: BaseException) -> str:
    if isinstance(exc, FusionError):
        status = exc.http_status if exc.http_status is not None else "-"
        return f"{exc.code.value} http={status} fusion={exc.fusion_code or '-'}"
    if isinstance(exc, _CheckFailedError):
        return str(exc)
    if isinstance(exc, TimeoutError):
        return "timeout"
    return type(exc).__name__


async def _run_one(
    name: str, check: Check, client: FusionClient, ctx: PreflightContext
) -> CheckResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(ctx.check_timeout_s):
            status, detail = await check(client, ctx)
    except Exception as exc:
        status, detail = CheckStatus.FAIL, _failure_detail(exc)
    elapsed = round((time.perf_counter() - started) * 1000)
    return CheckResult(name=name, status=status, detail=detail, elapsed_ms=elapsed)


async def run_preflight(client: FusionClient, ctx: PreflightContext) -> PreflightReport:
    """Run every check in order against `client` (callers pass a `read_only(...)` client)."""
    results = [await _run_one(name, check, client, ctx) for name, check in _checks()]
    return PreflightReport(pod_name=ctx.pod_name, env=ctx.env, results=tuple(results))
