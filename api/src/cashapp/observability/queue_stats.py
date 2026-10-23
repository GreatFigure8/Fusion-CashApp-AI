"""Queue depth and oldest-item age per stage and state, from one grouped query."""

from dataclasses import dataclass

from cashapp.data.repositories.queue_stats import QueueStatsRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.stages import PIPELINE_ORDER, TERMINAL_STATES, ItemState, Stage


@dataclass(frozen=True, slots=True)
class QueueStat:
    stage: Stage
    state: ItemState
    count: int
    oldest_age_s: float | None


async def collect_queue_stats(
    uow: UnitOfWork, *, clock: Clock | None = None, include_terminal: bool = False
) -> list[QueueStat]:
    """Read-only: no commit. Sorted by pipeline order, then state."""
    now = (clock if clock is not None else SystemClock()).now()
    rows = await uow.repo(QueueStatsRepository).grouped_counts(include_terminal=include_terminal)
    stats = [
        QueueStat(
            stage=row.stage,
            state=row.state,
            count=row.count,
            oldest_age_s=None
            if row.state in TERMINAL_STATES or row.oldest_at is None
            else round(max((now - row.oldest_at).total_seconds(), 0.0), 1),
        )
        for row in rows
    ]
    stats.sort(key=lambda stat: (PIPELINE_ORDER.index(stat.stage), stat.state.value))
    return stats
