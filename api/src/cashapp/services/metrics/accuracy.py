"""Field-level agreement between a reader's extraction and the human-corrected final.

Pure functions over the stored JSON documents. Invoice numbers are compared as strings, so a
``-1`` credit-memo suffix or a leading zero is never lost.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from cashapp.domain.money import money_eq, to_money

_HEADER_FIELDS: tuple[tuple[str, str], ...] = (
    ("payer_name", "payer_name"),
    ("remittance_reference", "remittance_reference"),
    ("payment_date", "payment_date"),
    ("amount", "payment_amount"),
    ("currency", "currency"),
)


def _scalar(node: Any) -> str | None:
    """The value of an ``Extracted`` node (or a bare scalar), as a stripped string."""
    value: Any = cast("Mapping[str, Any]", node).get("value") if isinstance(node, Mapping) else node
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_amount(key: str) -> bool:
    return key == "amount" or key.endswith(":amount_paid")


def _norm(key: str, raw: str | None) -> str:
    if raw is None:
        return ""
    if key == "currency":
        return raw.upper()
    if _is_amount(key):
        try:
            return f"{to_money(Decimal(raw)):.2f}"
        except (InvalidOperation, ValueError, TypeError):
            return raw
    return " ".join(raw.casefold().split())


def compared_fields(extraction: Mapping[str, Any]) -> dict[str, str]:
    """Normalised header fields plus ``line:<invoice_number>:amount_paid`` for every line."""
    fields: dict[str, str] = {}
    for key, source in _HEADER_FIELDS:
        fields[key] = _norm(key, _scalar(extraction.get(source)))
    lines = extraction.get("lines")
    if isinstance(lines, Sequence) and not isinstance(lines, str):
        for raw_line in cast("Sequence[Any]", lines):
            if not isinstance(raw_line, Mapping):
                continue
            line = cast("Mapping[str, Any]", raw_line)
            number = _scalar(line.get("transaction_number"))
            if number is None:
                continue
            key = f"line:{number}:amount_paid"
            fields[key] = _norm(key, _scalar(line.get("amount_paid")))
    return fields


def _equal(key: str, a: str, b: str) -> bool:
    if _is_amount(key) and a and b:
        try:
            return money_eq(Decimal(a), Decimal(b))
        except InvalidOperation:
            return a == b
    return a == b


def field_agreement(reading: Mapping[str, Any], human_final: Mapping[str, Any]) -> tuple[int, int]:
    """(matched, total) over every field the human final carries; a missing field is a miss."""
    final = compared_fields(human_final)
    seen = compared_fields(reading)
    matched = sum(1 for key, value in final.items() if _equal(key, seen.get(key, ""), value))
    return matched, len(final)


def differs(reading: Mapping[str, Any], human_final: Mapping[str, Any]) -> bool:
    """True when the human changed anything the reader produced."""
    matched, total = field_agreement(reading, human_final)
    return matched < total
