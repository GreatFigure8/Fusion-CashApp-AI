"""The replay items export. Cells a spreadsheet could read as a formula are neutralised."""

import csv
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal

from cashapp.domain.lab import CSV_FORMULA_PREFIXES

HEADER = (
    "item_id",
    "amount",
    "currency",
    "before",
    "after",
    "receipt_before",
    "receipt_after",
    "since_applied",
)


@dataclass(frozen=True, slots=True)
class CsvRow:
    item_id: int
    amount: Decimal | None
    currency: str | None
    before: str
    after: str
    receipt_before: int | None
    receipt_after: int | None
    since_applied: bool


def safe_cell(value: str) -> str:
    """Prefix a cell starting with = + - @ tab or CR with an apostrophe (CSV injection)."""
    return "'" + value if value.startswith(CSV_FORMULA_PREFIXES) else value


def _line(cells: Iterable[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\r\n").writerow(list(cells))
    return buffer.getvalue()


def replay_items_csv(rows: Iterable[CsvRow], *, header: bool = True) -> Iterator[str]:
    if header:
        yield _line(HEADER)
    for row in rows:
        yield _line(
            [
                str(row.item_id),
                f"{row.amount:.2f}" if row.amount is not None else "",
                safe_cell(row.currency or ""),
                safe_cell(row.before),
                safe_cell(row.after),
                str(row.receipt_before) if row.receipt_before is not None else "",
                str(row.receipt_after) if row.receipt_after is not None else "",
                "true" if row.since_applied else "false",
            ]
        )
