"""The one writer of work-item history rows."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cashapp.data.models.work_item import WorkItemHistory
from cashapp.data.types import to_jsonable
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME, ActorKind, HistoryAction


@dataclass(frozen=True)
class HistoryEntry:
    action: HistoryAction
    actor_kind: ActorKind = ActorKind.SYSTEM
    actor_id: str = SYSTEM_ACTOR_ID
    actor_name: str = SYSTEM_ACTOR_NAME
    from_stage: Stage | None = None
    to_stage: Stage | None = None
    from_state: ItemState | None = None
    to_state: ItemState | None = None
    error_code: ErrorCode | None = None
    reasoning: str | None = None
    payload: Mapping[str, Any] | None = None  # JSON-serialisable; Decimal becomes a string
    at: datetime | None = None  # None means clock.now()


async def record_history(
    uow: UnitOfWork, item_id: int, entry: HistoryEntry, *, clock: Clock | None = None
) -> WorkItemHistory:
    """Add a history row to the unit of work (flush, no commit)."""
    at = entry.at if entry.at is not None else (clock or SystemClock()).now()
    row = WorkItemHistory(
        work_item_id=item_id,
        at=at,
        actor_kind=entry.actor_kind,
        actor_id=entry.actor_id,
        actor_name=entry.actor_name,
        action=entry.action,
        from_stage=entry.from_stage,
        to_stage=entry.to_stage,
        from_state=entry.from_state,
        to_state=entry.to_state,
        error_code=entry.error_code,
        reasoning=entry.reasoning,
        payload=to_jsonable(dict(entry.payload)) if entry.payload is not None else None,
    )
    return await uow.history.add(row)
