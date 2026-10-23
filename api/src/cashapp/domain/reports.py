"""Report vocabulary: report kinds, who generated a report, and the aging buckets. Pure."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from types import MappingProxyType
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


class HtmlReportKind(StrEnum):
    """The kinds of self-contained HTML progress report. They differ only in default sections."""

    PROGRESS_SUMMARY = "PROGRESS_SUMMARY"
    EXCEPTIONS_AGING = "EXCEPTIONS_AGING"
    MODEL_EFFICIENCY = "MODEL_EFFICIENCY"


class ReportWindow(StrEnum):
    """The windows an HTML report offers. Values equal the metrics window of the same name."""

    D7 = "7d"
    D30 = "30d"
    MTD = "mtd"


class ReportSection(StrEnum):
    HEADLINE = "HEADLINE"
    MONEY_BY_CURRENCY = "MONEY_BY_CURRENCY"
    THROUGHPUT = "THROUGHPUT"
    EXCEPTIONS_BY_REASON = "EXCEPTIONS_BY_REASON"
    MODEL_EFFICIENCY = "MODEL_EFFICIENCY"


# Document order of the sections; also the order a request's sections are normalised to.
SECTION_ORDER: Final[tuple[ReportSection, ...]] = tuple(ReportSection)

DEFAULT_SECTIONS: Final[Mapping[HtmlReportKind, frozenset[ReportSection]]] = MappingProxyType(
    {
        HtmlReportKind.PROGRESS_SUMMARY: frozenset(
            {ReportSection.HEADLINE, ReportSection.MONEY_BY_CURRENCY, ReportSection.THROUGHPUT}
        ),
        HtmlReportKind.EXCEPTIONS_AGING: frozenset(
            {ReportSection.HEADLINE, ReportSection.EXCEPTIONS_BY_REASON}
        ),
        HtmlReportKind.MODEL_EFFICIENCY: frozenset(
            {ReportSection.HEADLINE, ReportSection.MODEL_EFFICIENCY}
        ),
    }
)

FILENAME_PREFIX: Final[Mapping[HtmlReportKind, str]] = MappingProxyType(
    {
        HtmlReportKind.PROGRESS_SUMMARY: "progress",
        HtmlReportKind.EXCEPTIONS_AGING: "exceptions",
        HtmlReportKind.MODEL_EFFICIENCY: "models",
    }
)


def report_filename(kind: HtmlReportKind, window: ReportWindow, day: date) -> str:
    """``progress_7d_2026-10-23.html``."""
    return f"{FILENAME_PREFIX[kind]}_{window.value}_{day.isoformat()}.html"
