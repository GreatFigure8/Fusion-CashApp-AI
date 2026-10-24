"""Chat tool ``metrics.read``: the dashboard's progress figures, read-only, over ``MetricsService``.

The handler is the same service the ``/metrics`` router calls. It opens its own unit of work and
never commits.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from cashapp.domain.metrics import MetricName, MetricsWindow
from cashapp.domain.principal import Permission
from cashapp.services.chat.tools.cards import (
    CardStat,
    CardStatus,
    ResultCard,
    StateCard,
    TableCard,
    TableColumn,
)
from cashapp.services.chat.tools.registry import ToolContext, ToolGroup, ToolSpec
from cashapp.services.config import RuntimeConfig
from cashapp.services.metrics.models import (
    ActivityEvent,
    AutofixOutcome,
    CurrencyTotal,
    ModelEfficiencyRow,
    ProgressSummary,
    ThroughputPoint,
)
from cashapp.services.metrics.service import MetricsService

_DESCRIPTION = (
    "Read the cash application progress figures for a window (24h, 7d, 30d or mtd). "
    "metric is one of: summary (receipts matched, automation rate, awaiting receipt, open "
    "exceptions), money_by_currency (applied per currency, never summed across currencies), "
    "throughput (applied and escalated per bucket), autofix (outcomes per error code), models "
    "(cost, agreement and accuracy where people corrected) or activity (recent events)."
)

MetricData = (
    ProgressSummary
    | list[CurrencyTotal]
    | list[ThroughputPoint]
    | list[AutofixOutcome]
    | list[ModelEfficiencyRow]
    | list[ActivityEvent]
)


class MetricsReadIn(BaseModel):
    metric: MetricName
    window: MetricsWindow = MetricsWindow.D7


class MetricsReadOut(BaseModel):
    metric: MetricName
    window: MetricsWindow
    as_of: datetime
    data: MetricData


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


async def read_metrics(ctx: ToolContext, args: MetricsReadIn) -> MetricsReadOut:
    config = await ctx.services.get(RuntimeConfig)
    async with ctx.uow_factory() as uow:  # read-only: leaving the block rolls back
        service = MetricsService(uow, clock=ctx.clock, config=config)
        data: MetricData
        match args.metric:
            case MetricName.SUMMARY:
                data = await service.summary(args.window)
            case MetricName.MONEY_BY_CURRENCY:
                data = await service.money_by_currency(args.window)
            case MetricName.THROUGHPUT:
                data = await service.throughput(args.window)
            case MetricName.AUTOFIX:
                data = await service.autofix_outcomes(args.window)
            case MetricName.MODELS:
                data = await service.model_efficiency(args.window)
            case MetricName.ACTIVITY:
                data = await service.recent_activity()
    return MetricsReadOut(metric=args.metric, window=args.window, as_of=ctx.clock.now(), data=data)


def _rows(items: list[Any]) -> list[dict[str, str | int | None]]:
    return [
        {k: (v if isinstance(v, int | str) or v is None else str(v)) for k, v in i.items()}
        for i in (item.model_dump(mode="json") for item in items)
    ]


_TABLES: dict[MetricName, tuple[str, list[TableColumn]]] = {
    MetricName.MONEY_BY_CURRENCY: (
        "Money applied by currency",
        [
            TableColumn(key="currency", label="Currency"),
            TableColumn(key="amount", label="Amount", numeric=True),
            TableColumn(key="receipts", label="Receipts", numeric=True),
            TableColumn(key="residual", label="Residual", numeric=True),
        ],
    ),
    MetricName.THROUGHPUT: (
        "Throughput",
        [
            TableColumn(key="at", label="Bucket (UTC)"),
            TableColumn(key="applied", label="Applied", numeric=True),
            TableColumn(key="escalated", label="Escalated", numeric=True),
        ],
    ),
    MetricName.AUTOFIX: (
        "Auto-fix outcomes",
        [
            TableColumn(key="error_code", label="Error code"),
            TableColumn(key="count", label="Items", numeric=True),
            TableColumn(key="fixed", label="Fixed", numeric=True),
        ],
    ),
    MetricName.MODELS: (
        "Model efficiency",
        [
            TableColumn(key="role", label="Role"),
            TableColumn(key="model_id", label="Model"),
            TableColumn(key="calls", label="Calls", numeric=True),
            TableColumn(key="cost_usd", label="Cost USD", numeric=True),
        ],
    ),
    MetricName.ACTIVITY: (
        "Recent activity",
        [
            TableColumn(key="at", label="At (UTC)"),
            TableColumn(key="kind", label="Kind"),
            TableColumn(key="text", label="What"),
        ],
    ),
}


def metrics_card(out: MetricsReadOut) -> ResultCard | None:
    data = out.data
    if isinstance(data, ProgressSummary):
        return StateCard(
            title=f"Progress · {out.window.value}",
            status=CardStatus(label="Live", tone="ok"),
            stats=[
                CardStat(label="Receipts matched", value=str(data.receipts_matched)),
                CardStat(label="Automation", value=_pct(data.automation_rate)),
                CardStat(label="Awaiting receipt", value=str(data.awaiting_receipt.count)),
                CardStat(label="Open exceptions", value=str(data.open_exceptions.total)),
            ],
        )
    title, columns = _TABLES[out.metric]
    return TableCard(
        title=f"{title} · {out.window.value}",
        columns=columns,
        rows=_rows(list(data)),
        total=len(data),
    )


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="metrics.read",
        group=ToolGroup.METRICS,
        description=_DESCRIPTION,
        input_model=MetricsReadIn,
        output_model=MetricsReadOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read progress metrics",
        handler=read_metrics,
        preview=None,
        card=metrics_card,
    )
]
