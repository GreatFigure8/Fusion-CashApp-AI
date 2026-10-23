"""What a station returns when it succeeds."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus


@dataclass(frozen=True, slots=True)
class Advance:
    """Move the item to ``next_stage`` and emit the event that wakes that station."""

    next_stage: Stage
    note: str = ""
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Park:
    """Hold the item until a receipt arrives (the receipt watcher wakes it)."""

    state: Literal[ItemState.AWAITING_RECEIPT] = ItemState.AWAITING_RECEIPT
    note: str = ""


@dataclass(frozen=True, slots=True)
class Finish:
    """The item is done; ``payment_status`` is the final roll-up."""

    payment_status: PaymentStatus
    note: str = ""


@dataclass(frozen=True, slots=True)
class Archive:
    """The item needs no further work (not a remittance, duplicate, and so on)."""

    reason: str


StageOutcome = Advance | Park | Finish | Archive
