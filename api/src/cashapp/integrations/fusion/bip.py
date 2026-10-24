"""The `DATA_DS/G_1` XML shape the report parsers read, and the pay-on-behalf relationships parser.

Rows now come from ad-hoc SQL run through the MCP server's `run_query` (datamodels/), rendered back
into the XML the callers already parse. There is no BI Publisher `runReport` call any more.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from typing import cast, get_args

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import CustomerRelationship, RelationshipDirection
from cashapp.integrations.fusion.xmlutil import (
    XmlParseError,
    child_text,
    iter_local,
    safe_fromstring,
)

RELATIONSHIPS_PARAM = "P_ACCOUNT_NUMBERS"

_DIRECTIONS: tuple[str, ...] = get_args(RelationshipDirection)


def rows_to_data_ds_xml(columns: Sequence[str], rows: Iterable[Sequence[object]]) -> bytes:
    """Render query rows as the BI Publisher `DATA_DS/G_1` XML the report parsers read.

    Column names are upper-cased; a `None` value omits its element; values are XML-escaped by the
    serializer. `Decimal` keeps its exact text.
    """
    names = [name.upper() for name in columns]
    root = ET.Element("DATA_DS")
    for row in rows:
        group = ET.SubElement(root, "G_1")
        for name, value in zip(names, row, strict=False):
            if value is None:
                continue
            ET.SubElement(group, name).text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
