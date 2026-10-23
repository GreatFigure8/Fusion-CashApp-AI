"""The flow monitor: live summary, the per-connection stream and the stage tables.

``/flow/stream`` is a view of the database for one open connection. It is not a poller of an
external source and it adds no third poller: each tick reads one indexed query for changed items
plus the process-wide cached summary.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from sse_starlette import EventSourceResponse

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.api.schemas.flow import (
    FlowStreamFrameOut,
    FlowSummaryOut,
    ItemChangedOut,
    StageItemsOut,
)
from cashapp.auth.deps import require_permission
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.domain.stages import ItemState
from cashapp.integrations.llm.cluster_metrics import build_cluster_metrics
from cashapp.services.flow_query import (
    OVERLAP_SECONDS,
    STREAM_TICK_SECONDS,
    BacklogProgressSource,
    CohereUtilisationSource,
    FlowSummaryCache,
    FlowSummaryData,
    FlowTile,
    default_backlog_source,
    default_cohere_source,
    flow_summary,
    items_changed_since,
    stage_items,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["flow"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]

PAGE_SIZE = 50
RESUME_WINDOW = timedelta(minutes=10)
CHANGED_LIMIT = 500
PING_SECONDS = 15


# --------------------------------------------------------------------------- dependencies


@lru_cache
def get_flow_summary_cache() -> FlowSummaryCache:
    """One cache per process; tests override this dependency."""
    return FlowSummaryCache()


async def get_cohere_source(runtime: RuntimeSettingsDep) -> CohereUtilisationSource:
    return default_cohere_source(await build_cluster_metrics(runtime))


def get_backlog_source(config: RuntimeConfigDep) -> BacklogProgressSource:
    return default_backlog_source(config)


@lru_cache
def get_clock() -> Clock:
    return SystemClock()


CacheDep = Annotated[FlowSummaryCache, Depends(get_flow_summary_cache)]
CohereDep = Annotated[CohereUtilisationSource, Depends(get_cohere_source)]
BacklogDep = Annotated[BacklogProgressSource, Depends(get_backlog_source)]
ClockDep = Annotated[Clock, Depends(get_clock)]


async def _summary(
    cache: FlowSummaryCache,
    uow_factory: UowFactory,
    clock: Clock,
    cohere: CohereUtilisationSource,
    backlog: BacklogProgressSource,
) -> FlowSummaryData:
    async def compute() -> FlowSummaryData:
        async with uow_factory() as uow:  # read-only: leaving the block rolls back
            return await flow_summary(uow, clock=clock, cohere=cohere, backlog=backlog)

    return await cache.get(compute)


# --------------------------------------------------------------------------- routes


@router.get("/flow/summary", response_model=FlowSummaryOut)
async def get_flow_summary(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    cache: CacheDep,
    clock: ClockDep,
    cohere: CohereDep,
    backlog: BacklogDep,
) -> FlowSummaryOut:
    return FlowSummaryOut.from_data(await _summary(cache, uow_factory, clock, cohere, backlog))


def _start_watermark(last_event_id: str | None, now: datetime) -> tuple[datetime, bool]:
    """Resume from ``Last-Event-ID`` when it is an ISO time within the last ten minutes."""
    if last_event_id:
        try:
            parsed = datetime.fromisoformat(last_event_id)
        except ValueError:
            return now, False
        if parsed.tzinfo is not None and now - RESUME_WINDOW <= parsed <= now:
            return parsed, True
    return now, False


def _frame(event: str, payload: str, event_id: str) -> dict[str, Any]:
    return {"event": event, "data": payload, "id": event_id}


@router.get(
    "/flow/stream",
    response_model=None,
    responses={200: {"model": FlowStreamFrameOut, "content": {"text/event-stream": {}}}},
)
async def stream_flow(
    request: Request,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    cache: CacheDep,
    clock: ClockDep,
    cohere: CohereDep,
    backlog: BacklogDep,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    watermark, resumed = _start_watermark(last_event_id, clock.now())

    async def frames() -> AsyncIterator[dict[str, Any]]:
        nonlocal watermark
        sent: dict[tuple[int, int], datetime] = {}
        first = not resumed
        while not await request.is_disconnected():
            try:
                summary = await _summary(cache, uow_factory, clock, cohere, backlog)
                now = clock.now()
                since = watermark if first else watermark - timedelta(seconds=OVERLAP_SECONDS)
                async with uow_factory() as uow:  # no session is held across the sleep
                    changed = await items_changed_since(uow, since, now=now, limit=CHANGED_LIMIT)
            except Exception as exc:
                logger.warning("flow stream tick failed: error=%s", type(exc).__name__)
                await asyncio.sleep(STREAM_TICK_SECONDS)
                continue
            first = False
            fresh = [c for c in changed if (c.id, c.version) not in sent]
            for change in changed:
                sent[(change.id, change.version)] = change.updated_at
                watermark = max(watermark, change.updated_at)
            horizon = watermark - timedelta(seconds=OVERLAP_SECONDS)
            for key in [k for k, at in sent.items() if at < horizon]:
                del sent[key]
            event_id = watermark.isoformat()
            yield _frame(
                "summary",
                FlowSummaryOut.from_data(summary).model_dump_json(by_alias=True),
                event_id,
            )
            for change in fresh:
                yield _frame(
                    "item_changed", ItemChangedOut.from_data(change).model_dump_json(), event_id
                )
            await asyncio.sleep(STREAM_TICK_SECONDS)

    return EventSourceResponse(frames(), ping=PING_SECONDS)


@router.get("/flow/stages/{tile}/items", response_model=StageItemsOut)
async def get_stage_items(
    tile: FlowTile,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    clock: ClockDep,
    state: ItemState | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> StageItemsOut:
    async with uow_factory() as uow:
        rows, total = await stage_items(
            uow, tile, state=state, page=page, page_size=PAGE_SIZE, now=clock.now()
        )
    return StageItemsOut.from_data(rows, total=total, page=page, page_size=PAGE_SIZE)
