"""How many auto-fix attempts an item has had, counted from its history.

The count comes from ``AUTOFIX_ATTEMPT`` rows after the item's latest ``HUMAN_ACTION`` row, not
from ``WORK_ITEM.ATTEMPTS``: the runner resets that counter on every advance, and a code can recur
across stages. A requeue by a person starts the count fresh. This is the one counting rule.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.repositories.autofix import AutoFixHistoryRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.error_codes import ErrorCode
from cashapp.services.config import ConfigSnapshot

NOOP_LOCKED: Final = "noop_locked"
"""The decision recorded when automation declined to act on a locked item (not an attempt)."""


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    at: datetime
    error_code: ErrorCode | None
    attempt: int
    limit: int
    decision: str
    reasoning: str | None


@dataclass(frozen=True, slots=True)
class AttemptSummary:
    tried: int
    limit: int
    attempts: tuple[AttemptRecord, ...]


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _record_of(row: WorkItemHistory) -> AttemptRecord:
    payload = row.payload or {}
    decision = payload.get("decision")
    return AttemptRecord(
        at=row.at,
        error_code=row.error_code,
        attempt=_int(payload.get("attempt")),
        limit=_int(payload.get("limit")),
        decision=decision if isinstance(decision, str) else "unknown",
        reasoning=row.reasoning,
    )


async def load_attempts(uow: UnitOfWork, item_id: int) -> list[AttemptRecord]:
    """Counted attempts since the latest human action, oldest first; no-op rows excluded."""
    repo = uow.repo(AutoFixHistoryRepository)
    since = await repo.latest_human_action_at(item_id)
    records = [_record_of(row) for row in await repo.autofix_rows_since(item_id, since)]
    return [record for record in records if record.decision != NOOP_LOCKED]


async def attempt_summary(
    uow: UnitOfWork, item: WorkItem, config: ConfigSnapshot
) -> AttemptSummary:
    """Tried and limit for the item's last error code, plus every counted attempt."""
    attempts = await load_attempts(uow, item.id)
    code = item.last_error_code
    if code is None:
        return AttemptSummary(tried=0, limit=0, attempts=tuple(attempts))
    tried = sum(1 for record in attempts if record.error_code == code)
    return AttemptSummary(
        tried=tried, limit=config.retries().max_attempts_for(code), attempts=tuple(attempts)
    )
