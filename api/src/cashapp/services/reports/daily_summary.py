"""The daily summary: counts, money applied and aging for one UTC day."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cashapp.data.repositories.reports import ReportQueryRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.reports import AGING_BUCKETS, bucket_for, day_bounds
from cashapp.services.reports.models import (
    AgingBucketCount,
    CurrencyAmount,
    DailySummary,
    ErrorCodeCount,
)

_ONE_DP = Decimal("0.1")
_HUNDRED = Decimal(100)
_SECONDS_PER_DAY = 86400


def percent(part: int, whole: int) -> Decimal | None:
    """``part / whole`` as a percentage at 1 dp, half-up. None when ``whole`` is zero."""
    if whole == 0:
        return None
    return (Decimal(part) * _HUNDRED / Decimal(whole)).quantize(_ONE_DP, rounding=ROUND_HALF_UP)


async def daily_summary(uow: UnitOfWork, day: date) -> DailySummary:
    start, end = day_bounds(day)
    queries = ReportQueryRepository(uow.session)

    items_in = await queries.items_in(start, end)
    completed, auto_applied = await queries.completions(start, end)
    applied = await queries.applied_by_currency(start, end)
    failures = await queries.failures_by_code(start, end)
    escalations = await queries.escalations(start, end)
    open_since = await queries.open_item_ages(end)

    counts = dict.fromkeys((bucket.key for bucket in AGING_BUCKETS), 0)
    for since in open_since:
        age_days = max(0, int((end - since).total_seconds() // _SECONDS_PER_DAY))
        counts[bucket_for(age_days).key] += 1

    return DailySummary(
        day=day,
        items_in=items_in,
        completed=completed,
        auto_applied=auto_applied,
        auto_applied_pct=percent(auto_applied, completed),
        applied_by_currency=tuple(CurrencyAmount(code, amount) for code, amount in applied),
        failures_by_error_code=tuple(ErrorCodeCount(code, count) for code, count in failures),
        aging_buckets=tuple(
            AgingBucketCount(bucket.key, bucket.label, counts[bucket.key])
            for bucket in AGING_BUCKETS
        ),
        escalations=escalations,
        has_activity=(items_in + completed + escalations + sum(count for _, count in failures)) > 0,
    )
