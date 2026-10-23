"""BI Publisher `runReport` envelope and the pay-on-behalf relationships report parser.

The service namespace, element names and the basic-auth assumption are UNVERIFIED (CONTRACTS.md).
"""

from __future__ import annotations

import base64
import binascii
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import cast, get_args

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import CustomerRelationship, RelationshipDirection
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    child_text,
    first_local,
    full_text,
    iter_local,
    safe_fromstring,
)

BIP_PATH = "/xmlpserver/services/ExternalReportWSSService"
BIP_NS = "http://xmlns.oracle.com/oxp/service/PublicReportService"  # UNVERIFIED
SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
RELATIONSHIPS_PARAM = "P_ACCOUNT_NUMBERS"

_DIRECTIONS: tuple[str, ...] = get_args(RelationshipDirection)


def build_run_report_envelope(path: str, params: Mapping[str, str], fmt: str) -> bytes:
    ET.register_namespace("soapenv", SOAP_ENV_NS)
    ET.register_namespace("pub", BIP_NS)
    envelope = ET.Element(f"{{{SOAP_ENV_NS}}}Envelope")
    ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Header")
    body = ET.SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    run = ET.SubElement(body, f"{{{BIP_NS}}}runReport")
    request = ET.SubElement(run, f"{{{BIP_NS}}}reportRequest")
    ET.SubElement(request, f"{{{BIP_NS}}}attributeFormat").text = fmt
    ET.SubElement(request, f"{{{BIP_NS}}}reportAbsolutePath").text = path
    ET.SubElement(request, f"{{{BIP_NS}}}sizeOfDataChunkDownload").text = "-1"
    values = ET.SubElement(request, f"{{{BIP_NS}}}parameterNameValues")
    for name, value in params.items():
        item = ET.SubElement(values, f"{{{BIP_NS}}}item")
        ET.SubElement(item, f"{{{BIP_NS}}}name").text = name
        holder = ET.SubElement(item, f"{{{BIP_NS}}}values")
        ET.SubElement(holder, f"{{{BIP_NS}}}item").text = value
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def parse_run_report_response(xml: bytes) -> bytes:
    """Return the Base64-decoded `reportBytes`; any fault or malformed envelope is an error."""
    try:
        root = safe_fromstring(xml)
    except XmlParseError as exc:
        raise FusionError(ErrorCode.FUSION_FAULT, "unparseable BI Publisher response") from exc
    fault = first_local(root, "Fault")
    if fault is not None:
        text = full_text(fault)[:300] or "BI Publisher fault"
        raise FusionError(ErrorCode.FUSION_FAULT, text)
    report = first_local(root, "reportBytes")
    if report is None or not (report.text or "").strip():
        raise FusionError(ErrorCode.FUSION_FAULT, "BI Publisher response has no reportBytes")
    try:
        return base64.b64decode((report.text or "").strip(), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise FusionError(ErrorCode.FUSION_FAULT, "reportBytes is not valid Base64") from exc


def parse_relationships_xml(data: bytes) -> list[CustomerRelationship]:
    """Parse the pinned row shape; one relationship per (account, related) with all directions."""
    try:
        root = safe_fromstring(data)
    except XmlParseError as exc:
        raise FusionError(ErrorCode.FUSION_FAULT, "unparseable relationships report") from exc
    merged: dict[tuple[str, str], tuple[str | None, set[RelationshipDirection]]] = {}
    for row in iter_local(root, "G_1"):
        account = child_text(row, "ACCOUNT_NUMBER")
        related = child_text(row, "RELATED_ACCOUNT_NUMBER")
        direction = (child_text(row, "DIRECTION") or "").upper()
        if account is None or related is None or account == related:
            continue
        if direction not in _DIRECTIONS:
            continue
        name, directions = merged.setdefault(
            (account, related), (child_text(row, "RELATED_ACCOUNT_NAME"), set())
        )
        directions.add(cast(RelationshipDirection, direction))
        if name is None:
            merged[(account, related)] = (child_text(row, "RELATED_ACCOUNT_NAME"), directions)
    return [
        CustomerRelationship(
            account_number=account,
            related_account_number=related,
            related_account_name=name,
            directions=frozenset(directions),
        )
        for (account, related), (name, directions) in merged.items()
    ]
