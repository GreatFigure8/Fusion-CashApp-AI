"""Report vocabulary: report kinds, who generated a report, and the aging buckets. Pure."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Final


class ReportKind(StrEnum):
    DAILY_SUMMARY = "DAILY_SUMMARY"


GENERATED_BY_CUTOVER: Final = "first-event-after-cutover"
GENERATED_BY_USER_PREFIX: Final = "user:"


@dataclass(frozen=True, slots=True)
class AgingBucket:
    key: str
    label: str
    min_days: int
    max_days: int | None


# One definition of the awaiting-receipt aging buckets; the flow monitor imports it too.
AGING_BUCKETS: Final[tuple[AgingBucket, ...]] = (
    AgingBucket("0-2d", "0-2 days", 0, 2),
    AgingBucket("3-7d", "3-7 days", 3, 7),
    AgingBucket("8-30d", "8-30 days", 8, 30),
    AgingBucket("gt30d", "Over 30 days", 31, None),
)


def bucket_for(age_days: int) -> AgingBucket:
    """The bucket a whole-day age falls in. A negative age is a caller error."""
    if age_days < 0:
        raise ValueError(f"age_days must not be negative, got {age_days}")
    for bucket in AGING_BUCKETS:
        if bucket.max_days is None or age_days <= bucket.max_days:
            return bucket
    return AGING_BUCKETS[-1]  # unreachable: the last bucket is open-ended


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The UTC window ``[day 00:00Z, day+1 00:00Z)`` a report day covers."""
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)
