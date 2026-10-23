"""Helpers handlers use to write ``FIX_HINTS`` and to pick which readers to re-run."""

from typing import Literal, cast

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.extraction import ReaderSlot, ReadingStatus
from cashapp.domain.work_item import FixHints
from cashapp.pipeline.errors import StageError

_LADDER: dict[str | None, Literal["medium", "high", "max"]] = {
    None: "high",
    "low": "medium",
    "medium": "high",
    "high": "max",
    "max": "max",
}


def replace_fix_hints(item: WorkItem, hints: FixHints) -> None:
    """Replace the hints wholesale (never merge), so a stale ``rerun_readers`` cannot linger."""
    item.fix_hints = FixHints(**hints)


def bump_effort(effort: str | None) -> Literal["medium", "high", "max"]:
    """One step up the effort ladder: low to medium to high to max; unknown becomes high."""
    return _LADDER.get(effort, "high")


def _slots_from(raw: object) -> list[Literal["A", "B"]]:
    if not isinstance(raw, list):
        return []
    found: list[Literal["A", "B"]] = []
    for entry in cast("list[object]", raw):
        if entry == "A" and "A" not in found:
            found.append("A")
        elif entry == "B" and "B" not in found:
            found.append("B")
    return found


async def failed_readers(
    uow: UnitOfWork, item: WorkItem, error: StageError
) -> list[Literal["A", "B"]]:
    """The readers to re-run: the error's own list, else those whose latest reading is not OK,
    else both."""
    named = _slots_from(error.detail.get("failed_readers"))
    if named:
        return named
    latest = await uow.repo(ExtractionReadingRepository).latest_for(item.id)
    failed: list[Literal["A", "B"]] = []
    for slot, label in ((ReaderSlot.A, "A"), (ReaderSlot.B, "B")):
        reading = latest.get(slot)
        if reading is None or reading.status != ReadingStatus.OK:
            failed.append("A" if label == "A" else "B")
    return failed if failed else ["A", "B"]
