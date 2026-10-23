"""Progress metrics: the dashboard's aggregates and a per-connection live stream.

Every route is a view of the database through ``MetricsService``. ``/metrics/stream`` is not a
poller of an external source and emits nothing to the bus: each open connection reads the shared
``MetricsChangeFeed`` once per tick (the same mechanism as ``/flow/stream``).
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from sse_starlette import EventSourceResponse

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.routers.flow import PING_SECONDS, ClockDep
from cashapp.api.schemas.metrics import (
    ActivityOut,
    AutofixOut,
    MetricsStreamErrorFrame,
    MetricsSummaryFrame,
    ModelsOut,
    MoneyByCurrencyOut,
    SummaryOut,
    ThroughputOut,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.metrics import MetricsWindow, ThroughputBucket
from cashapp.domain.principal import Permission, Principal
from cashapp.services.flow_query import STREAM_TICK_SECONDS
from cashapp.services.metrics.activity import to_activity
from cashapp.services.metrics.feed import MetricsChangeFeed
from cashapp.services.metrics.service import MetricsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["metrics"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.REPORTS_READ))]
WindowQuery = Annotated[MetricsWindow, Query(description="24h, 7d, 30d or mtd")]

ACTIVITY_DEFAULT = 50
ACTIVITY_MAX = 200
STREAM_BATCH = 200
STREAM_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache, no-transform"}


@lru_cache
def get_metrics_feed() -> MetricsChangeFeed:
    """One feed per process; tests override this dependency."""
    return MetricsChangeFeed()


FeedDep = Annotated[MetricsChangeFeed, Depends(get_metrics_feed)]


@router.get("/summary", response_model=SummaryOut)
async def get_summary(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
) -> SummaryOut:
    async with uow_factory() as uow:  # read-only: leaving the block rolls back
        data = await MetricsService(uow, clock=clock, config=config).summary(window)
    return SummaryOut(window=window, as_of=clock.now(), data=data)


@router.get("/money-by-currency", response_model=MoneyByCurrencyOut)
async def get_money_by_currency(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
) -> MoneyByCurrencyOut:
    async with uow_factory() as uow:
        data = await MetricsService(uow, clock=clock, config=config).money_by_currency(window)
    return MoneyByCurrencyOut(window=window, as_of=clock.now(), data=data)


@router.get("/throughput", response_model=ThroughputOut)
async def get_throughput(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
    bucket: ThroughputBucket | None = None,
) -> ThroughputOut:
    async with uow_factory() as uow:
        data = await MetricsService(uow, clock=clock, config=config).throughput(window, bucket)
    return ThroughputOut(window=window, as_of=clock.now(), data=data)


@router.get("/autofix", response_model=AutofixOut)
async def get_autofix(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
) -> AutofixOut:
    async with uow_factory() as uow:
        data = await MetricsService(uow, clock=clock, config=config).autofix_outcomes(window)
    return AutofixOut(window=window, as_of=clock.now(), data=data)


@router.get("/models", response_model=ModelsOut)
async def get_models(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
) -> ModelsOut:
    async with uow_factory() as uow:
        data = await MetricsService(uow, clock=clock, config=config).model_efficiency(window)
    return ModelsOut(window=window, as_of=clock.now(), data=data)


@router.get("/activity", response_model=ActivityOut)
async def get_activity(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    window: WindowQuery = MetricsWindow.D7,
    limit: Annotated[int, Query(ge=1, le=ACTIVITY_MAX)] = ACTIVITY_DEFAULT,
) -> ActivityOut:
    async with uow_factory() as uow:
        data = await MetricsService(uow, clock=clock, config=config).recent_activity(limit)
    return ActivityOut(window=window, as_of=clock.now(), data=data)


def _frame(event: str, payload: str, event_id: int) -> dict[str, Any]:
    return {"event": event, "data": payload, "id": str(event_id)}


def _resume_id(last_event_id: str | None) -> int | None:
    if last_event_id is None:
        return None
    try:
        value = int(last_event_id)
    except ValueError:
        return None
    return value if value >= 0 else None


@router.get(
    "/stream",
    response_model=None,
    responses={
        200: {
            "model": MetricsSummaryFrame,
            "description": "event: summary / activity / stream-error",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_metrics(
    request: Request,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    clock: ClockDep,
    feed: FeedDep,
    window: WindowQuery = MetricsWindow.D7,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    resume = _resume_id(last_event_id)

    async def frames() -> AsyncIterator[dict[str, Any]]:
        cursor = resume
        last_summary: str | None = None
        try:
            while not await request.is_disconnected():
                latest = await feed.latest_id(uow_factory)
                if cursor is None:
                    cursor = latest
                    changed = True  # the first frame always carries the summary
                else:
                    rows = await feed.since(uow_factory, cursor, STREAM_BATCH)
                    for event in to_activity(rows):
                        yield _frame("activity", event.model_dump_json(), event.id)
                    if rows:
                        cursor = max(cursor, rows[-1].id)
                    changed = latest > cursor or bool(rows)
                    cursor = max(cursor, latest)
                if changed or last_summary is None:
                    summary = await feed.summary(
                        uow_factory, clock=clock, config=config, window=window
                    )
                    fingerprint = summary.model_dump_json(exclude={"start", "end"})
                    if fingerprint != last_summary:
                        last_summary = fingerprint
                        envelope = MetricsSummaryFrame(
                            window=window, as_of=clock.now(), data=summary
                        )
                        yield _frame("summary", envelope.model_dump_json(), cursor)
                await asyncio.sleep(STREAM_TICK_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("metrics stream tick failed: error=%s", type(exc).__name__)
            error = MetricsStreamErrorFrame(
                code="METRICS_STREAM_FAILED", message="The live metrics stream stopped."
            )
            yield _frame("stream-error", error.model_dump_json(), cursor or 0)

    return EventSourceResponse(frames(), ping=PING_SECONDS, headers=STREAM_HEADERS)
