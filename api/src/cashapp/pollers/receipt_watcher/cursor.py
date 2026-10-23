"""The watcher's cursor arithmetic, pure so it is easy to prove.

Fusion is asked for ``CreationDate >= mark - OVERLAP``. A receipt is new when its id has not been
emitted yet, so a receipt that becomes visible late (created inside the overlap window) is still
emitted, and a tie at the mark across cycles is not emitted twice.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final

from cashapp.integrations.fusion.models import FusionReceipt

OVERLAP: Final = timedelta(minutes=5)
INITIAL_LOOKBACK: Final = timedelta(hours=24)


def select_new(
    receipts: Sequence[FusionReceipt],
    mark: datetime,
    seen: Mapping[str, str],
    overlap: timedelta = OVERLAP,
) -> list[FusionReceipt]:
    """The receipts to emit, in Fusion's order (creation ascending, id ascending)."""
    floor = mark - overlap
    taken: set[int] = set()
    fresh: list[FusionReceipt] = []
    for receipt in receipts:
        if receipt.creation_date < floor:
            continue
        if str(receipt.receipt_id) in seen or receipt.receipt_id in taken:
            continue
        taken.add(receipt.receipt_id)
        fresh.append(receipt)
    return fresh


def advance_mark(
    mark: datetime,
    seen: Mapping[str, str],
    emitted: Sequence[FusionReceipt],
    overlap: timedelta = OVERLAP,
) -> tuple[datetime, dict[str, str]]:
    """The new mark (never backwards) and the seen map, pruned to the overlap window."""
    new_mark = max([mark, *(r.creation_date for r in emitted)])
    merged = dict(seen)
    for receipt in emitted:
        merged[str(receipt.receipt_id)] = receipt.creation_date.isoformat()
    floor = new_mark - overlap
    pruned = {rid: at for rid, at in merged.items() if datetime.fromisoformat(at) >= floor}
    return new_mark, pruned
