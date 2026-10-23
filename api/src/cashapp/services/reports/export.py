"""CSV and XLSX files for both reports, with stable column headers.

Cells are written as values, never formulas. Free text that came from a remittance (payer names,
reasons) is untrusted, so a string that a spreadsheet could read as a formula is prefixed with a
single quote.
"""

import csv
import io
from collections.abc import Callable, Sequence
from datetime import date
from decimal import Decimal
from typing import Final, Literal

from openpyxl import Workbook
from openpyxl.cell.cell import Cell

from cashapp.domain.money import to_money
from cashapp.services.reports.models import DailySummary, PartiallyPaidRow

ExportFormat = Literal["csv", "xlsx"]

DAILY_SUMMARY_COLUMNS: Final[tuple[str, ...]] = ("section", "key", "currency", "value")
PARTIALLY_PAID_COLUMNS: Final[tuple[str, ...]] = (
    "invoice_number",
    "customer_account_number",
    "customer_name",
    "currency",
    "original",
    "paid",
    "remaining",
    "short_pay_reason",
    "item_id",
)

CSV_TYPE: Final = "text/csv; charset=utf-8"
XLSX_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MONEY_FORMAT: Final = "#,##0.00"
PERCENT_FORMAT: Final = "0.0"

_FORMULA_TRIGGERS: Final = ("=", "+", "-", "@", "\t", "\r")

# A cell value: text, a whole number, or a Decimal (money and percentages).
type Cellish = str | int | Decimal | None
type Row = tuple[Cellish, ...]


def safe_text(value: str | None) -> str:
    """Neutralise formula injection in untrusted text."""
    if not value:
        return ""
    return "'" + value if value.startswith(_FORMULA_TRIGGERS) else value


def _money(value: Decimal) -> str:
    return f"{to_money(value):.2f}"


def _daily_rows(summary: DailySummary) -> list[Row]:
    pct = summary.auto_applied_pct
    rows: list[Row] = [
        ("kpi", "items_in", "", summary.items_in),
        ("kpi", "completed", "", summary.completed),
        ("kpi", "auto_applied", "", summary.auto_applied),
        ("kpi", "auto_applied_pct", "", pct),
        ("kpi", "escalations", "", summary.escalations),
    ]
    rows += [
        ("applied_by_currency", "amount_applied", row.currency, to_money(row.amount))
        for row in summary.applied_by_currency
    ]
    rows += [
        ("failures_by_error_code", row.error_code.value, "", row.count)
        for row in summary.failures_by_error_code
    ]
    rows += [("aging", row.key, "", row.count) for row in summary.aging_buckets]
    return rows


def _partially_paid_rows(rows: Sequence[PartiallyPaidRow]) -> list[Row]:
    return [
        (
            safe_text(row.invoice_number),
            safe_text(row.customer_account_number),
            safe_text(row.customer_name),
            row.currency,
            to_money(row.original),
            to_money(row.paid),
            to_money(row.remaining),
            safe_text(row.short_pay_reason),
            row.item_id,
        )
        for row in rows
    ]


def _csv_cell(value: Cellish, section: str, key: str) -> str | int:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        # The percentage is shown at 1 dp; everything else Decimal is money at 2 dp.
        return f"{value:.1f}" if (section, key) == ("kpi", "auto_applied_pct") else _money(value)
    return value


def _to_csv(columns: Sequence[str], rows: Sequence[Row], daily: bool) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        if daily:
            section, key = str(row[0]), str(row[1])
            writer.writerow([row[0], row[1], row[2], _csv_cell(row[3], section, key)])
        else:
            writer.writerow([_csv_cell(cell, "", "") for cell in row])
    return buffer.getvalue().encode("utf-8")


def _set(cell: Cell, value: Cellish, number_format: str | None) -> None:
    if isinstance(value, str):
        cell.value = value
        cell.data_type = "s"  # text, never a formula
        return
    cell.value = value
    if number_format is not None and value is not None:
        cell.number_format = number_format


def _to_xlsx(
    title: str,
    columns: Sequence[str],
    rows: Sequence[Row],
    number_format_for: Callable[[Row, int], str | None],
) -> bytes:
    book = Workbook()
    sheet = book.active
    if sheet is None:  # a new Workbook always has an active sheet
        raise RuntimeError("workbook has no active sheet")
    sheet.title = title
    sheet.append(list(columns))
    sheet.freeze_panes = "A2"
    for row_index, row in enumerate(rows, start=2):
        for column_index, value in enumerate(row):
            cell = sheet.cell(row=row_index, column=column_index + 1)
            if isinstance(cell, Cell):
                _set(cell, value, number_format_for(row, column_index))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _daily_format(row: Row, column: int) -> str | None:
    if column != 3 or not isinstance(row[3], Decimal):
        return None
    return PERCENT_FORMAT if row[1] == "auto_applied_pct" else MONEY_FORMAT


_PARTIALLY_PAID_MONEY_COLUMNS: Final = frozenset({4, 5, 6})


def _partially_paid_format(row: Row, column: int) -> str | None:
    return MONEY_FORMAT if column in _PARTIALLY_PAID_MONEY_COLUMNS else None


def daily_summary_file(summary: DailySummary, fmt: ExportFormat) -> tuple[str, bytes, str]:
    """(filename, content, content type), the shape of an email attachment."""
    rows = _daily_rows(summary)
    name = f"daily-summary-{summary.day.isoformat()}.{fmt}"
    if fmt == "csv":
        return name, _to_csv(DAILY_SUMMARY_COLUMNS, rows, daily=True), CSV_TYPE
    return name, _to_xlsx("Daily summary", DAILY_SUMMARY_COLUMNS, rows, _daily_format), XLSX_TYPE


def partially_paid_file(
    rows: Sequence[PartiallyPaidRow], from_: date, to: date, fmt: ExportFormat
) -> tuple[str, bytes, str]:
    cells = _partially_paid_rows(rows)
    name = f"partially-paid-{from_.isoformat()}_{to.isoformat()}.{fmt}"
    if fmt == "csv":
        return name, _to_csv(PARTIALLY_PAID_COLUMNS, cells, daily=False), CSV_TYPE
    xlsx = _to_xlsx("Partially paid", PARTIALLY_PAID_COLUMNS, cells, _partially_paid_format)
    return name, xlsx, XLSX_TYPE
