"""The exception worklist: items a person has to look at, with their auto-fix progress and lock."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.exceptions import (
    AWAITING_EXCEPTION_AFTER,
    FAILED_LINE_STATUSES,
    ExceptionsRepository,
)
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.paging import Page
from cashapp.domain.principal import Principal
from cashapp.domain.stages import Stage
from cashapp.services.autofix.attempts import NOOP_LOCKED
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.config_groups import RetriesConfig
from cashapp.services.locking import LockInfo, lock_info_for

__all__ = [
    "AWAITING_EXCEPTION_AFTER",
    "FAILED_LINE_STATUSES",
    "ExceptionFilters",
    "ExceptionRow",
    "ExceptionsQueryService",
]


@dataclass(frozen=True, slots=True)
class ExceptionFilters:
    q: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    date_from: date | None = None
    date_to: date | None = None
    error_codes: tuple[ErrorCode, ...] = ()
    stage: Stage | None = None
    locked_by_me: bool = False
    include_auto_applied: bool = False
    include_archived: bool = False
    page: int = 1
    page_size: int = 50
    sort: str = "-age"


@dataclass(frozen=True, slots=True)
class ExceptionRow:
    item: WorkItem
    autofix_tried: int
    autofix_limit: int
    age_s: int
    lock: LockInfo | None


class ExceptionsQueryService:
    def __init__(self, config: RuntimeConfig | ConfigSnapshot, clock: Clock | None = None) -> None:
        self._config = config
        self._clock: Clock = clock or SystemClock()

    async def _retries(self) -> RetriesConfig:
        config = self._config
        return await config.retries() if isinstance(config, RuntimeConfig) else config.retries()

    async def list(
        self, uow: UnitOfWork, filters: ExceptionFilters, principal: Principal
    ) -> Page[ExceptionRow]:
        now = self._clock.now()
        repo = uow.repo(ExceptionsRepository)
        page = await repo.search(filters, subject=principal.subject, now=now)
        tried = await repo.autofix_counts(page.items, ignore_decisions=(NOOP_LOCKED,))
        retries = await self._retries()
        rows = [
            ExceptionRow(
                item=item,
                autofix_tried=tried.get(item.id, 0),
                autofix_limit=(
                    retries.max_attempts_for(item.last_error_code) if item.last_error_code else 0
                ),
                age_s=max(0, int((now - _aware(item.created_at)).total_seconds())),
                lock=lock_info_for(item, now),
            )
            for item in page.items
        ]
        return Page(items=rows, total=page.total, offset=page.offset, limit=page.limit)


def _aware(moment: datetime) -> datetime:
    """Timestamps from the database are UTC; treat a naive one as UTC rather than failing."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
