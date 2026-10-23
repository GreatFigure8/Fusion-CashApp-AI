"""Read-side reports over the usage ledger: daily totals, one item's calls, Cohere utilisation."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from cashapp.data.repositories.llm_usage import LlmUsageRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.llm_usage import LlmRole, UsageGroupBy, UsageOutcome
from cashapp.integrations.llm.cluster_metrics import ClusterMetrics

__all__ = [
    "CohereUtilisation",
    "DailyUsage",
    "UsageCall",
    "cohere_utilisation",
    "daily_usage",
    "item_usage",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DailyUsage:
    day: date
    station: str | None
    model: str | None
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal  # sum of known costs; see unpriced_calls before treating it as complete
    unpriced_calls: int


@dataclass(frozen=True, slots=True)
class UsageCall:
    id: int
    created_at: datetime
    station: str
    purpose: str
    role: LlmRole
    provider: str
    model_id: str
    prompt_version: str | None
    schema_version: str | None
    effort: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    cost_usd: Decimal | None
    outcome: UsageOutcome
    error_code: str | None


@dataclass(frozen=True, slots=True)
class CohereUtilisation:
    window_minutes: int
    busy_seconds: float
    calls: int
    utilisation_pct: float
    cluster_utilisation_pct: float | None

    @property
    def best_pct(self) -> float:
        """The cluster's own metric when present, else the ledger-derived value."""
        if self.cluster_utilisation_pct is not None:
            return self.cluster_utilisation_pct
        return self.utilisation_pct


async def daily_usage(
    uow: UnitOfWork, *, from_day: date, to_day: date, group_by: UsageGroupBy
) -> list[DailyUsage]:
    rows = await uow.repo(LlmUsageRepository).daily(
        from_day=from_day, to_day=to_day, group_by=group_by
    )
    by_station = group_by == UsageGroupBy.STATION
    return [
        DailyUsage(
            day=row.day,
            station=row.key if by_station else None,
            model=None if by_station else row.key,
            calls=row.calls,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cost_usd=row.cost_usd,
            unpriced_calls=row.unpriced_calls,
        )
        for row in rows
    ]


async def item_usage(uow: UnitOfWork, item_id: int) -> list[UsageCall]:
    return [
        UsageCall(
            id=row.id,
            created_at=row.created_at,
            station=row.station,
            purpose=row.purpose,
            role=row.role,
            provider=row.provider,
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            schema_version=row.schema_version,
            effort=row.effort,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            latency_ms=row.latency_ms,
            cost_usd=row.cost_usd,
            outcome=row.outcome,
            error_code=row.error_code,
        )
        for row in await uow.repo(LlmUsageRepository).for_item(item_id)
    ]


async def cohere_utilisation(
    uow: UnitOfWork,
    *,
    window_minutes: int = 60,
    clock: Clock | None = None,
    cluster: ClusterMetrics | None = None,
) -> CohereUtilisation:
    """How busy the Cohere reader has been over the window.

    ``utilisation_pct`` is busy time over wall time and is deliberately not capped at 100:
    concurrent calls can overlap, and capping would hide saturation.
    """
    now = (clock or SystemClock()).now()
    since = now - timedelta(minutes=window_minutes)
    latency_ms, calls = await uow.repo(LlmUsageRepository).busy_since(LlmRole.READER_B, since)
    busy_seconds = round(latency_ms / 1000, 1)
    utilisation_pct = round(busy_seconds / (window_minutes * 60) * 100, 1)
    cluster_pct: float | None = None
    if cluster is not None and cluster.configured:
        try:
            measured = await cluster.utilisation(window_minutes)
        except Exception as exc:
            logger.warning("cluster_utilisation_failed", extra={"error_type": type(exc).__name__})
        else:
            cluster_pct = measured.pct if measured is not None else None
    return CohereUtilisation(
        window_minutes=window_minutes,
        busy_seconds=busy_seconds,
        calls=calls,
        utilisation_pct=utilisation_pct,
        cluster_utilisation_pct=cluster_pct,
    )
