"""Progress-metrics vocabulary: windows, buckets, activity kinds and the window arithmetic.

The one definition used by ``MetricsService``, the ``/metrics`` router, the chat tool and the
progress reports.
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum


class MetricsWindow(StrEnum):
    H24 = "24h"
    D7 = "7d"
    D30 = "30d"
    MTD = "mtd"


class ThroughputBucket(StrEnum):
    HOUR = "hour"
    DAY = "day"


class ActivityKind(StrEnum):
    APPLIED = "APPLIED"
    RECEIPT_ARRIVED = "RECEIPT_ARRIVED"
    AUTOFIX = "AUTOFIX"
    ESCALATED = "ESCALATED"


class MetricName(StrEnum):
    SUMMARY = "summary"
    MONEY_BY_CURRENCY = "money_by_currency"
    THROUGHPUT = "throughput"
    AUTOFIX = "autofix"
    MODELS = "models"
    ACTIVITY = "activity"


class CostBasis(StrEnum):
    PER_CALL = "PER_CALL"
    CLUSTER = "CLUSTER"


_WINDOW_SPAN: dict[MetricsWindow, timedelta] = {
    MetricsWindow.H24: timedelta(hours=24),
    MetricsWindow.D7: timedelta(days=7),
    MetricsWindow.D30: timedelta(days=30),
}


def window_bounds(window: MetricsWindow, now: datetime) -> tuple[datetime, datetime]:
    """The half-open window ``[start, end)`` ending at ``now`` (UTC). ``mtd`` starts on the 1st."""
    end = now.astimezone(UTC)
    if window is MetricsWindow.MTD:
        return end.replace(day=1, hour=0, minute=0, second=0, microsecond=0), end
    return end - _WINDOW_SPAN[window], end


def default_bucket(window: MetricsWindow) -> ThroughputBucket:
    """Hourly buckets for 24h, daily for every longer window."""
    return ThroughputBucket.HOUR if window is MetricsWindow.H24 else ThroughputBucket.DAY


def bucket_start(at: datetime, bucket: ThroughputBucket) -> datetime:
    """Truncate ``at`` to the start of its bucket (UTC)."""
    utc = at.astimezone(UTC)
    if bucket is ThroughputBucket.HOUR:
        return utc.replace(minute=0, second=0, microsecond=0)
    return utc.replace(hour=0, minute=0, second=0, microsecond=0)


def bucket_step(bucket: ThroughputBucket) -> timedelta:
    return timedelta(hours=1) if bucket is ThroughputBucket.HOUR else timedelta(days=1)
