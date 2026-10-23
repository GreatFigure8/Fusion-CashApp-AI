"""API contracts for the progress metrics: one envelope, concrete aliases and the SSE frames."""

import datetime as dt

from pydantic import BaseModel

from cashapp.domain.metrics import MetricsWindow
from cashapp.services.metrics.models import (
    ActivityEvent,
    AutofixOutcome,
    CurrencyTotal,
    ModelEfficiencyRow,
    ProgressSummary,
    ThroughputPoint,
)


class MetricsEnvelope[T](BaseModel):
    window: MetricsWindow
    as_of: dt.datetime
    data: T


class SummaryOut(MetricsEnvelope[ProgressSummary]): ...


class MoneyByCurrencyOut(MetricsEnvelope[list[CurrencyTotal]]): ...


class ThroughputOut(MetricsEnvelope[list[ThroughputPoint]]): ...


class AutofixOut(MetricsEnvelope[list[AutofixOutcome]]): ...


class ModelsOut(MetricsEnvelope[list[ModelEfficiencyRow]]): ...


class ActivityOut(MetricsEnvelope[list[ActivityEvent]]): ...


class MetricsSummaryFrame(SummaryOut):
    """SSE ``event: summary``. Documentation only; the stream serialises it directly."""


class MetricsActivityFrame(ActivityEvent):
    """SSE ``event: activity``, one per new history row."""


class MetricsStreamErrorFrame(BaseModel):
    """SSE ``event: stream-error``, the last frame when a tick fails after the stream started."""

    code: str
    message: str
