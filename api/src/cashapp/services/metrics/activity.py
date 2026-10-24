"""Map history rows to the live activity feed.

The text is built from structured fields only (item id, currency and amount, receipt number,
error-code description). Payer names and reasoning text never enter a broadcast feed.
"""

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

from cashapp.data.repositories.metrics import HistoryActivityRow
from cashapp.domain.metrics import ActivityKind
from cashapp.domain.money import to_money
from cashapp.domain.stages import ItemState
from cashapp.domain.work_item import HistoryAction
from cashapp.services.metrics.models import ActivityEvent


def _kind(row: HistoryActivityRow) -> ActivityKind | None:
    if row.action is HistoryAction.FUSION_WRITE:
        applied = row.error_code is None and row.payload is not None and "ledger_id" in row.payload
        return ActivityKind.APPLIED if applied else None
    if row.action is HistoryAction.AUTOFIX_ATTEMPT:
        return ActivityKind.AUTOFIX
    if row.to_state is ItemState.ESCALATED:
        return ActivityKind.ESCALATED
    if (
        row.from_state is ItemState.AWAITING_RECEIPT
        and row.to_state is not ItemState.AWAITING_RECEIPT
    ):
        return ActivityKind.RECEIPT_ARRIVED
    return None


def _amount(row: HistoryActivityRow) -> str:
    raw = row.payload.get("amount") if row.payload else None
    if raw is None:
        return ""
    try:
        text = f"{to_money(Decimal(str(raw))):.2f}"
    except (InvalidOperation, ValueError):
        return ""
    return f"{row.currency} {text}" if row.currency else text


def _code_label(row: HistoryActivityRow) -> str:
    return row.error_code.spec.description if row.error_code is not None else "no error code"


def _receipt(row: HistoryActivityRow) -> str:
    return f"RCPT-{row.receipt_number}" if row.receipt_number else "a receipt"


def _text(kind: ActivityKind, row: HistoryActivityRow) -> str:
    item = f"WI-{row.work_item_id}"
    if kind is ActivityKind.APPLIED:
        amount = _amount(row)
        head = f"{item} · {amount} to {_receipt(row)}" if amount else f"{item} · {_receipt(row)}"
        return head
    if kind is ActivityKind.RECEIPT_ARRIVED:
        return f"{_receipt(row)} woke {item}"
    return f"{item} {_code_label(row)}"


def to_activity(rows: Sequence[HistoryActivityRow]) -> list[ActivityEvent]:
    """Events in the order given. Consecutive RECEIPT_ARRIVED rows for one receipt merge into
    "RCPT-x woke N waiting items" (the merged event keeps the first row's id and time)."""
    events: list[ActivityEvent] = []
    run_key: str | None = None
    run_count = 0
    for row in rows:
        kind = _kind(row)
        if kind is None:
            run_key = None
            continue
        key = row.receipt_number if kind is ActivityKind.RECEIPT_ARRIVED else None
        if key is not None and key == run_key and events:
            run_count += 1
            first = events[-1]
            events[-1] = first.model_copy(
                update={"text": f"{_receipt(row)} woke {run_count} waiting items", "item_id": None}
            )
            continue
        run_key = key
        run_count = 1
        events.append(
            ActivityEvent(
                id=row.id,
                at=row.at,
                kind=kind,
                item_id=row.work_item_id,
                text=_text(kind, row),
            )
        )
    return events
