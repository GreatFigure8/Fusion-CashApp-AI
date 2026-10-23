"""SOAP envelopes and fail-closed parsing for `StandardReceiptService`.

Namespaces, the SOAPAction values and the unapply operation are UNVERIFIED (see CONTRACTS.md).
Envelopes are built with ElementTree so values are escaped by the serializer, never formatted in.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import (
    FusionFault,
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
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    child_text,
    first_local,
    full_text,
    iter_local,
    local_name,
    safe_fromstring,
)

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
