"""The note written to a Fusion receipt: a counted, truncating, deterministic template.

Pure: no I/O and no LLM. The note carries only the item id, date, counts, currency, amounts and
transaction numbers; never payer names, email text or source file names.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Literal, Protocol

from cashapp.domain.money import to_money
from cashapp.domain.status import APPLIED_LINE_STATUSES, LineStatus

NOTE_PREFIX: Final = "CashApp WI-{id} {date}:"
NOTE_SEPARATOR: Final = " | "
PRIOR_NOTE_MARKER: Final = "[earlier note replaced]"

WriteBackMode = Literal["applied", "already_applied"]

SHORT_REASONS: Mapping[LineStatus, str] = MappingProxyType(
    {
        LineStatus.ALLOCATION_INVOICE_NOT_FOUND: "not found",
        LineStatus.ALLOCATION_CUSTOMER_NOT_FOUND: "no customer",
        LineStatus.ALLOCATION_NO_REMAINING_BALANCE: "no balance",
        LineStatus.ALLOCATION_ZERO_AMOUNT: "zero amount",
        LineStatus.ALLOCATION_MISSING_PAYMENT_DATE: "no date",
        LineStatus.ALLOCATION_NO_RECEIPT_MATCH: "no receipt",
        LineStatus.ALLOCATION_APPLY_FAILED: "apply failed",
        LineStatus.ALLOCATION_DRY_RUN: "dry run",
    }
)

_SEE_APP = " See app."
_ELLIPSIS = "…"
_TRANSACTION_MAX = 30


class NoteItem(Protocol):
    @property
    def id(self) -> int: ...

    @property
    def currency(self) -> str | None: ...


class NoteLine(Protocol):
    @property
    def line_no(self) -> int: ...

    @property
    def transaction_number(self) -> str | None: ...

    @property
    def line_status(self) -> LineStatus | None: ...

    @property
    def applied_amount(self) -> Decimal | None: ...


def _clean_number(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:_TRANSACTION_MAX] or None


def _reason(status: LineStatus | None) -> str:
    if status is None:
        return "pending"
    return SHORT_REASONS.get(status, status.value)


def _failed_entry(line: NoteLine) -> str:
    label = _clean_number(line.transaction_number) or f"line {line.line_no}"
    return f"{label} {_reason(line.line_status)}"


def _fit_header(header: str, max_chars: int) -> str:
    """Header plus the closing hint; the header alone is cut with an ellipsis if still too long."""
    text = header + _SEE_APP
    if len(text) <= max_chars:
        return text
    if len(header) <= max_chars:
        return header
    return header[: max(max_chars - 1, 0)] + _ELLIPSIS


def note_segment(
    item: NoteItem,
    line_results: Sequence[NoteLine],
    *,
    mode: WriteBackMode,
    on: date,
    max_chars: int,
) -> str:
    """This item's part of the note. ``len(result) <= max_chars`` always."""
    prefix = NOTE_PREFIX.format(id=item.id, date=on.isoformat())
    lines = sorted(line_results, key=lambda ln: ln.line_no)
    previously = [ln for ln in lines if ln.line_status is LineStatus.ALLOCATION_PREVIOUSLY_APPLIED]

    if mode == "already_applied":
        count = len(previously) or len(lines)
        header = f"{prefix} remittance received; {count} invoice(s) already applied."
        return _fit_header(header, max_chars)[:max_chars]

    applied = [ln for ln in lines if ln.line_status in APPLIED_LINE_STATUSES]
    total = to_money(sum((ln.applied_amount or Decimal(0) for ln in applied), Decimal(0)))
    currency = item.currency or "?"
    header = f"{prefix} applied {len(applied)}/{len(lines)} ({currency} {total:,.2f})."
    if previously:
        header += f" Prev applied {len(previously)}."

    failed = [
        _failed_entry(ln)
        for ln in lines
        if ln.line_status not in APPLIED_LINE_STATUSES
        and ln.line_status is not LineStatus.ALLOCATION_PREVIOUSLY_APPLIED
    ]
    for kept in range(len(failed), -1, -1):
        omitted = len(failed) - kept
        parts = failed[:kept]
        if omitted:
            parts = [*parts, f"{_ELLIPSIS}+{omitted} more"]
        if not parts:
            break
        candidate = f"{header} Failed: {'; '.join(parts)}.{_SEE_APP}"
        if len(candidate) <= max_chars:
            return candidate
    return _fit_header(header, max_chars)[:max_chars]


def merge_note(existing: str | None, segment: str, *, work_item_id: int, max_chars: int) -> str:
    """Append ``segment`` to the existing note, replacing this item's earlier segment.

    Keeps the previous text when everything fits; otherwise the previous text is replaced by a
    marker (or dropped when even the marker does not fit).
    """
    own = f"CashApp WI-{work_item_id} "
    kept = [
        part
        for part in (existing or "").split(NOTE_SEPARATOR)
        if part.strip() and not part.startswith(own) and part != PRIOR_NOTE_MARKER
    ]
    if not kept:
        return segment
    combined = NOTE_SEPARATOR.join([*kept, segment])
    if len(combined) <= max_chars:
        return combined
    marked = f"{PRIOR_NOTE_MARKER}{NOTE_SEPARATOR}{segment}"
    return marked if len(marked) <= max_chars else segment


def compose_receipt_note(
    item: NoteItem,
    line_results: Sequence[NoteLine],
    max_chars: int,
    *,
    existing: str | None = None,
    mode: WriteBackMode = "applied",
    on: date,
) -> str:
    segment = note_segment(item, line_results, mode=mode, on=on, max_chars=max_chars)
    return merge_note(existing, segment, work_item_id=item.id, max_chars=max_chars)
