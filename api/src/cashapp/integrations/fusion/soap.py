"""The direct SOAP path to Fusion: envelopes, fail-closed parsing and the HTTP transport.

`SoapTransport` is the only code in the package that opens an HTTP client to a Fusion host. Reads
and REST writes go through the MCP server (mcp_client.py); only `createApplyReceipt` and
`createUnapplyReceipt` (and the `?WSDL` probe) come here. Nothing logs or traces a URL query, a
body or a credential: only method, pod, HTTP status, attempt, latency and a Fusion code.

Namespaces, the SOAPAction values and the unapply operation are UNVERIFIED (see CONTRACTS.md).
Envelopes are built with ElementTree so values are escaped by the serializer, never formatted in.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import (
    FusionError,
    FusionFault,
    error_from_http,
    fault_from_messages,
    is_noise,
)
from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    FusionMessage,
    UnapplyRequest,
    UnapplyResult,
)
from cashapp.domain.config_keys import FusionPod
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    child_text,
    first_local,
    full_text,
    iter_local,
    local_name,
    safe_fromstring,
)
from cashapp.observability.logging import get_logger
from cashapp.observability.tracing import span

_log = get_logger(__name__)

SOAP_PATH_RECEIPTS = "/fscmService/StandardReceiptService"
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
# UNVERIFIED: service namespaces and operation element names, confirm against the WSDL.
RECEIPT_TYPES_NS = (
    "http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/"
    "publicService/standardReceiptService/types/"
)
RECEIPT_NS = (
    "http://xmlns.oracle.com/apps/financials/receivables/receipts/shared/"
    "publicService/standardReceiptService/"
)
SOAP_ACTION_APPLY = "createApplyReceipt"  # UNVERIFIED
SOAP_ACTION_UNAPPLY = "createUnapplyReceipt"  # UNVERIFIED (s38)

_CODE_RE = re.compile(r"\b(AR-\d{6}|ORA-\d{5})\b")
_TOKEN_RE = re.compile(r"\b([A-Z]{2,}(?:_[A-Z0-9]+)+)\b")


def accounting_date_for(payment_date: date, today: date) -> date:
    """Application and accounting date: the later of the payment date and today."""
    return max(payment_date, today)


def _money_text(value: Decimal) -> str:
    return f"{value:.2f}"


def _envelope(operation: str, fields: list[tuple[str, str]]) -> bytes:
    ET.register_namespace("soapenv", SOAP_ENV_NS)
    ET.register_namespace("typ", RECEIPT_TYPES_NS)
    ET.register_namespace("rec", RECEIPT_NS)
    envelope = ET.Element(f"{{{SOAP_ENV_NS}}}Envelope")
    ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Header")
    body = ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    op = ET.SubElement(body, f"{{{RECEIPT_TYPES_NS}}}{operation}")
    for name, value in fields:
        ET.SubElement(op, f"{{{RECEIPT_TYPES_NS}}}{name}").text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def build_apply_envelope(request: ApplyRequest) -> bytes:
    fields: list[tuple[str, str]] = [
        ("ReceiptId", str(request.receipt_id)),
        ("CustomerTrxId", str(request.customer_trx_id)),
        ("AmountApplied", _money_text(request.amount_applied)),
        ("ReceiptCurrency", request.receipt_currency),  # UNVERIFIED element name
        ("ApplicationDate", request.application_date.isoformat()),
        ("AccountingDate", request.accounting_date.isoformat()),
    ]
    if request.discount_amount is not None:
        fields.append(("DiscountTaken", _money_text(request.discount_amount)))  # UNVERIFIED
    return _envelope("createApplyReceipt", fields)


def build_unapply_envelope(request: UnapplyRequest) -> bytes:
    # UNVERIFIED (s38): operation and element names.
    return _envelope(
        "createUnapplyReceipt",
        [
            ("ReceiptId", str(request.receipt_id)),
            ("ReceivableApplicationId", str(request.application_id)),
            ("ReversalGlDate", request.reversal_gl_date.isoformat()),
            ("ReversalComments", request.reason),
        ],
    )


def _code_from_text(text: str) -> str | None:
    match = _CODE_RE.search(text) or _TOKEN_RE.search(text)
    return match.group(1) if match else None


def _message(code: str | None, severity: str | None, text: str) -> FusionMessage:
    text = " ".join(text.split())
    return FusionMessage(code=code or _code_from_text(text), severity=severity, text=text)


def _collect_messages(root: ET.Element) -> list[FusionMessage]:
    messages: list[FusionMessage] = []
    for fault_string in iter_local(root, "faultstring"):
        text = full_text(fault_string)
        if text:
            messages.append(_message(None, "FAULT", text))
    for name in ("ServiceErrorMessage", "ServiceMessage"):
        for element in iter_local(root, name):
            code = child_text(element, "code")
            text = child_text(element, "message") or child_text(element, "text")
            severity = child_text(element, "severity") or child_text(element, "type")
            messages.append(_message(code, severity, text or full_text(element)))
    return messages


def _failure(
    code: ErrorCode,
    text: str,
    messages: tuple[FusionMessage, ...],
    *,
    fusion_code: str | None = None,
) -> FusionFault:
    return FusionFault(code=code, fusion_code=fusion_code, message=text, messages=messages)


def _parse(xml: bytes) -> tuple[ET.Element | None, tuple[FusionMessage, ...], FusionFault | None]:
    """Shared fail-closed core: (root, all messages, fault)."""
    try:
        root = safe_fromstring(xml)
    except XmlParseError:
        return None, (), _failure(ErrorCode.FUSION_FAULT, "unparseable response", ())
    messages = tuple(_collect_messages(root))
    real = tuple(m for m in messages if not is_noise(m))
    fault = fault_from_messages(real)
    if fault is None and first_local(root, "Fault") is not None:
        # A Fault element with no usable message is still a failure.
        fault = _failure(ErrorCode.FUSION_FAULT, "SOAP fault without a message", messages)
    return root, messages, fault


def parse_apply_response(xml: bytes, *, receipt_id: int) -> ApplyResult:
    """Fail closed: ok only when a `Value` block exists and no real fault or message remains."""
    root, messages, fault = _parse(xml)
    if root is None or fault is not None:
        return ApplyResult(
            ok=False, application_id=None, fault=fault, raw_messages=messages, receipt_id=receipt_id
        )
    value = first_local(root, "Value")
    if value is None:
        return ApplyResult(
            ok=False,
            application_id=None,
            fault=_failure(ErrorCode.FUSION_FAULT, "no Value block in response", messages),
            raw_messages=messages,
            receipt_id=receipt_id,
        )
    application_id = _application_id(value)
    return ApplyResult(
        ok=True,
        application_id=application_id,
        fault=None,
        raw_messages=messages,
        receipt_id=receipt_id,
    )


def _application_id(value: ET.Element) -> int | None:
    for element in value.iter():
        if local_name(element.tag) == "ReceivableApplicationId":  # UNVERIFIED element
            text = (element.text or "").strip()
            if text.isdigit():
                return int(text)
    return None


def parse_unapply_response(xml: bytes) -> UnapplyResult:
    root, messages, fault = _parse(xml)
    if root is None or fault is not None:
        return UnapplyResult(ok=False, fault=fault, raw_messages=messages)
    if first_local(root, "Value") is None:
        return UnapplyResult(
            ok=False,
            fault=_failure(ErrorCode.FUSION_FAULT, "no Value block in response", messages),
            raw_messages=messages,
        )
    return UnapplyResult(ok=True, fault=None, raw_messages=messages)


# --- transport ----------------------------------------------------------------------------

SleepFn = Callable[[float], Awaitable[None]]

# Failures where Fusion certainly did not process the request: safe to retry a write.
_NOT_PROCESSED = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_WRITE_RETRY_STATUS = frozenset({401, 503})


PasswordProvider = Callable[[], Awaitable[SecretStr]]


class PodAuth(httpx.Auth):
    """Basic auth whose password is resolved from Vault on every request (TTL-cached there), so
    a rotated secret is picked up without a restart and is never held by the client."""

    def __init__(self, username: str, password: PasswordProvider) -> None:
        self._username = username
        self._password = password

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        secret = (await self._password()).get_secret_value()
        token = base64.b64encode(f"{self._username}:{secret}".encode()).decode("ascii")
        request.headers["Authorization"] = f"Basic {token}"
        yield request


@dataclass(frozen=True, slots=True)
class SoapOptions:
    timeout_s: float = 60.0
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0


class SoapTransport:
    """HTTP Basic client for the pod's SOAP services with bounded retry and backoff."""

    def __init__(
        self,
        *,
        pod_name: str,
        pod: FusionPod,
        password: PasswordProvider,
        options: SoapOptions = SoapOptions(),  # noqa: B008 - frozen value object
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.pod_name = pod_name
        self.options = options
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=pod.base_url,
            auth=PodAuth(pod.username, password),
            timeout=options.timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _delay(self, attempt: int) -> float:
        cap = min(self.options.backoff_max_s, self.options.backoff_base_s * (2 ** (attempt - 1)))
        return random.uniform(0, cap)  # noqa: S311 - jitter, not security

    async def _request(
        self,
        method: str,
        url: str,
        *,
        op: str,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        write: bool = False,
        soap_fault_ok: bool = False,
    ) -> httpx.Response:
        """Send with bounded retry. Returns the response for 2xx (and SOAP-fault 500s if allowed).

        Reads retry every transient failure. Writes retry only when Fusion certainly did not
        process the request; any other transient write failure raises `outcome_unknown=True`.
        """
        started = time.perf_counter()
        last_error: FusionError | None = None
        attempts = 0
        with span(f"fusion.{op}", pod=self.pod_name) as active:
            for attempt in range(1, self.options.max_attempts + 1):
                attempts = attempt
                try:
                    response = await self._client.request(
                        method, url, content=content, headers=headers
                    )
                except httpx.TransportError as exc:  # TimeoutException is a TransportError
                    certain = isinstance(exc, _NOT_PROCESSED)
                    last_error = FusionError(
                        ErrorCode.FUSION_TRANSIENT,
                        f"{type(exc).__name__} calling Fusion",
                        outcome_unknown=write and not certain,
                    )
                    retry = certain or not write
                else:
                    if response.is_success or (
                        soap_fault_ok
                        and response.status_code == 500
                        and b"Fault" in response.content
                    ):
                        self._finish(op, response.status_code, attempts, started, None)
                        active.set(status=response.status_code, attempts=attempts)
                        return response
                    error = error_from_http(response.status_code, response.content)
                    if not error.retryable:
                        self._finish(op, response.status_code, attempts, started, error)
                        active.set(status=response.status_code, attempts=attempts)
                        raise error
                    if write:
                        retry = response.status_code in _WRITE_RETRY_STATUS
                        error.outcome_unknown = not retry
                    else:
                        retry = True
                    last_error = error
                if not retry or attempt >= self.options.max_attempts:
                    break
                await self._sleep(self._delay(attempt))
            assert last_error is not None  # noqa: S101 - loop always sets it before breaking
            self._finish(op, last_error.http_status, attempts, started, last_error)
            active.set(status=last_error.http_status or 0, attempts=attempts)
            raise last_error

    def _finish(
        self,
        op: str,
        status: int | None,
        attempts: int,
        started: float,
        error: FusionError | None,
    ) -> None:
        _log.info(
            "fusion call",
            extra={
                "fusion_method": op,
                "pod": self.pod_name,
                "http_status": status,
                "attempts": attempts,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "fusion_code": error.code.value if error else None,
            },
        )

    async def post_soap(
        self, url: str, envelope: bytes, *, action: str, op: str, write: bool
    ) -> bytes:
        response = await self._request(
            "POST",
            url,
            op=op,
            content=envelope,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": action,
                "Accept": "text/xml",
            },
            write=write,
            soap_fault_ok=True,
        )
        return response.content

    async def get_wsdl(self, path: str) -> bytes:
        """`GET <path>?WSDL` with the read retry policy (the preflight and contract probe)."""
        response = await self._request("GET", f"{path}?WSDL", op="get_wsdl")
        return response.content
