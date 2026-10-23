"""A field-level diff between two extractions, for the requeue history row and the workbench."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel

from cashapp.domain.extraction import ExtractedLine, RemittanceExtraction
from cashapp.domain.money import to_money

type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None

_LINE_FIELDS = (
    "kind",
    "transaction_number",
    "amount_paid",
    "gross_amount",
    "discount_claimed",
    "deduction",
    "po_number",
    "sales_order",
    "ers_reference",
)


@dataclass(frozen=True, slots=True)
class FieldChange:
    path: str
    before: JsonValue
    after: JsonValue


def _json(value: Any) -> JsonValue:
    """Plain JSON; Decimal as a 2 dp string, dates as ISO text, enums as their value."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return f"{to_money(value):.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json(value.value)
    if isinstance(value, BaseModel):
        return _json(value.model_dump(mode="json"))
    if isinstance(value, list | tuple):
        return [_json(entry) for entry in cast("Sequence[Any]", value)]
    if isinstance(value, dict):
        return {str(key): _json(entry) for key, entry in cast("dict[Any, Any]", value).items()}
    if hasattr(value, "amount") and hasattr(value, "currency"):
        return {"amount": _json(value.amount), "currency": _json(value.currency)}
    return str(value)


def _flatten(extraction: RemittanceExtraction | None) -> dict[str, JsonValue]:
    if extraction is None:
        return {}
    flat: dict[str, JsonValue] = {
        "payer_name": _json(extraction.payer_name.value),
        "payer_bank_account": _json(extraction.payer_bank_account.value),
        "remittance_reference": _json(extraction.remittance_reference.value),
        "payment_amount": _json(extraction.payment_amount.value),
        "currency_raw": _json(extraction.currency_raw.value),
        "currency": _json(extraction.currency.value),
        "currency_ambiguous": extraction.currency_ambiguous,
        "payment_date": _json(extraction.payment_date.value),
        "dates": [
            {"value": _json(candidate.value), "kind": _json(candidate.kind)}
            for candidate in extraction.dates
        ],
        "po_refs": list(extraction.po_refs),
        "sales_order_refs": list(extraction.sales_order_refs),
        "ers_refs": list(extraction.ers_refs),
        "bank_fees": _json(extraction.bank_fees),
        "notes": extraction.notes,
    }
    for line in extraction.lines:
        for name in _LINE_FIELDS:
            flat[f"lines[{line.line_no}].{name}"] = _json(getattr(line, name))
    return flat


def _line_numbers(extraction: RemittanceExtraction | None) -> set[int]:
    return {line.line_no for line in extraction.lines} if extraction is not None else set()


def _line_summary(line: ExtractedLine) -> JsonValue:
    return {name: _json(getattr(line, name)) for name in _LINE_FIELDS}


def _line_of(extraction: RemittanceExtraction | None, line_no: int) -> ExtractedLine | None:
    if extraction is None:
        return None
    return next((line for line in extraction.lines if line.line_no == line_no), None)


def extraction_diff(
    before: RemittanceExtraction | None, after: RemittanceExtraction
) -> list[FieldChange]:
    """Changed header values, the dates list, changed line fields, and added or removed lines."""
    old, new = _flatten(before), _flatten(after)
    old_lines, new_lines = _line_numbers(before), _line_numbers(after)
    changes: list[FieldChange] = []
    for path, after_value in new.items():
        if path.startswith("lines["):
            continue
        if before is None or old.get(path) != after_value:
            changes.append(FieldChange(path, old.get(path), after_value))
    for line_no in sorted(old_lines | new_lines):
        prefix = f"lines[{line_no}]"
        if line_no not in old_lines:
            added = _line_of(after, line_no)
            changes.append(
                FieldChange(prefix, None, _line_summary(added) if added is not None else None)
            )
        elif line_no not in new_lines:
            removed = _line_of(before, line_no)
            changes.append(
                FieldChange(prefix, _line_summary(removed) if removed is not None else None, None)
            )
        else:
            for name in _LINE_FIELDS:
                path = f"{prefix}.{name}"
                if old.get(path) != new.get(path):
                    changes.append(FieldChange(path, old.get(path), new.get(path)))
    return changes
