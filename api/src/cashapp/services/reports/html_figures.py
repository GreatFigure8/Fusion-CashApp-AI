"""The figures an HTML progress report shows, gathered from the one metrics owner.

Every number comes from ``MetricsService``, the existing aging query and the exceptions worklist.
This module computes nothing new: it only decides which of those calls a report's sections need
and carries the results to the renderer. It imports no SQLAlchemy.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from cashapp.domain.metrics import MetricsWindow, ThroughputBucket, window_bounds
from cashapp.domain.principal import Principal
from cashapp.domain.reports import HtmlReportKind, ReportSection, ReportWindow
from cashapp.services.exceptions_query import ExceptionFilters, ExceptionsQueryService
from cashapp.services.metrics.models import (
    AutofixOutcome,
    CurrencyTotal,
    ModelEfficiencyRow,
    ProgressSummary,
    ThroughputPoint,
)
from cashapp.services.metrics.service import MetricsService
from cashapp.services.reports.daily_summary import aging_counts
from cashapp.services.reports.models import AgingBucketCount

if TYPE_CHECKING:
    from cashapp.data.uow import UnitOfWork

OLDEST_EXCEPTIONS = 5


@dataclass(frozen=True, slots=True)
class Caveats:
    """What the footnote may claim. Only measured values; ``None`` means unmeasured."""

    accuracy_n: int
    cost_unknown_share: Decimal | None
    model_calls: int


@dataclass(frozen=True, slots=True)
class OldestException:
    item_id: int
    payer: str | None
    amount: Decimal | None
    currency: str | None
    age_days: int


@dataclass(frozen=True, slots=True)
class ReportFigures:
    kind: HtmlReportKind
    window: ReportWindow
    sections: frozenset[ReportSection]
    start: datetime
    end: datetime
    as_of: datetime
    summary: ProgressSummary
    money: tuple[CurrencyTotal, ...]
    throughput: tuple[ThroughputPoint, ...]
    exceptions_by_reason: tuple[AutofixOutcome, ...]
    aging: tuple[AgingBucketCount, ...]
    oldest_exceptions: tuple[OldestException, ...]
    models: tuple[ModelEfficiencyRow, ...]
    caveats: Caveats
    has_data: bool


def caveats_for(models: tuple[ModelEfficiencyRow, ...]) -> Caveats:
    """Accuracy n summed; cost-unknown share weighted by calls over rows that measured it."""
    accuracy_n = sum(row.accuracy_n for row in models)
    calls = sum(row.calls for row in models)
    measured = [row for row in models if row.cost_unknown_share is not None]
    measured_calls = sum(row.calls for row in measured)
    share: Decimal | None = None
    if measured_calls > 0:
        weighted = sum(
            (Decimal(str(row.cost_unknown_share)) * row.calls for row in measured),
            start=Decimal(0),
        )
        share = weighted / Decimal(measured_calls)
    return Caveats(accuracy_n=accuracy_n, cost_unknown_share=share, model_calls=calls)


async def gather_figures(
    uow: "UnitOfWork",
    metrics: MetricsService,
    exceptions: ExceptionsQueryService,
    principal: Principal,
    kind: HtmlReportKind,
    window: ReportWindow,
    sections: frozenset[ReportSection],
    now: datetime,
) -> ReportFigures:
    """Call only the metrics methods the selected sections need.

    The summary is always read: the range line and the "is there anything to report" test need it.
    """
    metrics_window = MetricsWindow(window.value)
    start, end = window_bounds(metrics_window, now)
    summary = await metrics.summary(metrics_window)

    money: tuple[CurrencyTotal, ...] = ()
    if ReportSection.MONEY_BY_CURRENCY in sections:
        money = tuple(await metrics.money_by_currency(metrics_window))

    throughput: tuple[ThroughputPoint, ...] = ()
    if ReportSection.THROUGHPUT in sections:
        throughput = tuple(await metrics.throughput(metrics_window, ThroughputBucket.DAY))

    by_reason: tuple[AutofixOutcome, ...] = ()
    aging: tuple[AgingBucketCount, ...] = ()
    oldest: tuple[OldestException, ...] = ()
    if ReportSection.EXCEPTIONS_BY_REASON in sections:
        by_reason = tuple(await metrics.autofix_outcomes(metrics_window))
        if kind is HtmlReportKind.EXCEPTIONS_AGING:
            aging = await aging_counts(uow, now)
            page = await exceptions.list(
                uow, ExceptionFilters(page_size=OLDEST_EXCEPTIONS, sort="-age"), principal
            )
            oldest = tuple(
                OldestException(
                    item_id=row.item.id,
                    payer=row.item.payer_name,
                    amount=row.item.payment_amount,
                    currency=row.item.currency,
                    age_days=row.age_s // 86400,
                )
                for row in page.items
            )

    models: tuple[ModelEfficiencyRow, ...] = ()
    if ReportSection.MODEL_EFFICIENCY in sections:
        models = tuple(await metrics.model_efficiency(metrics_window))

    has_data = summary.done_items > 0 or any(
        point.applied > 0 or point.escalated > 0 for point in throughput
    )
    return ReportFigures(
        kind=kind,
        window=window,
        sections=sections,
        start=start,
        end=end,
        as_of=now,
        summary=summary,
        money=money,
        throughput=throughput,
        exceptions_by_reason=by_reason,
        aging=aging,
        oldest_exceptions=oldest,
        models=models,
        caveats=caveats_for(models),
        has_data=has_data,
    )
