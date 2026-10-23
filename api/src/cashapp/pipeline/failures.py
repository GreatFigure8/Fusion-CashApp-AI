"""What the auto-fix engine (s18) may decide when a station raises a ``StageError``."""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UnitOfWork
from cashapp.domain.stages import Stage
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import StageOutcome

if TYPE_CHECKING:
    from cashapp.pipeline.runner import StageContext


@dataclass(frozen=True, slots=True)
class Retry:
    """Run the same stage again after ``after`` (through the stage's retry topic)."""

    after: timedelta


@dataclass(frozen=True, slots=True)
class ParkAwaitingReceipt:
    """Wait in AWAITING_RECEIPT until the receipt watcher wakes the item."""


@dataclass(frozen=True, slots=True)
class Escalate:
    """Hand the item to a person. ``summary`` is kept if s18 already set one."""

    summary: str | None = None


@dataclass(frozen=True, slots=True)
class Reroute:
    """Send the item back (or forward) to another stage."""

    stage: Stage


@dataclass(frozen=True, slots=True)
class Resolved:
    """The failure was repaired; apply ``outcome`` as if the station had returned it."""

    outcome: StageOutcome


FailureDecision = Retry | ParkAwaitingReceipt | Escalate | Reroute | Resolved


def decision_kind(decision: FailureDecision) -> str:
    match decision:
        case Retry():
            return "retry"
        case ParkAwaitingReceipt():
            return "park"
        case Escalate():
            return "escalate"
        case Reroute():
            return "reroute"
        case Resolved():
            return "resolved"


class FailureHandler(Protocol):
    """Implemented by the auto-fix engine. May mutate ``item`` hints and write history on
    ``uow``; must not commit."""

    async def handle(
        self, uow: UnitOfWork, item: WorkItem, error: StageError, ctx: "StageContext"
    ) -> FailureDecision: ...


class EscalateAllHandler:
    """The default until s18 lands: every failure goes to a person."""

    async def handle(
        self, uow: UnitOfWork, item: WorkItem, error: StageError, ctx: "StageContext"
    ) -> FailureDecision:
        return Escalate(None)
