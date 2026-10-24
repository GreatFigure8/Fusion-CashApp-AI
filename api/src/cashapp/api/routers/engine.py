"""Engine control: live status, pause / resume / drain per station, throttle, dead-letter replay.

Reads need ``reports:read`` (operators see the board); every mutation needs ``engine:control``
and carries a reason and the ``expected_version`` the screen loaded. Status is computed on
request (shared by a short per-process cache); the stream is a view of that status for one open
connection. There is no background task here.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sse_starlette import EventSourceResponse

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.engine_deps import EngineServiceDep, engine_api_error
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.schemas.engine import (
    DeadLetterOut,
    DeadLetterPage,
    EngineActionIn,
    EngineActionOut,
    EngineAuditOut,
    EngineAuditPage,
    EngineStatusOut,
    ReplayIn,
    ReplayOut,
    ThrottleIn,
)
from cashapp.auth.deps import require_permission
from cashapp.domain import config_keys as ck
from cashapp.domain.engine import Station
from cashapp.domain.principal import Permission, Principal
from cashapp.services.config import ConfigError
from cashapp.services.engine.service import EngineError, require_station

logger = logging.getLogger(__name__)

router = APIRouter(tags=["engine"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.REPORTS_READ))]
ControllerDep = Annotated[Principal, Depends(require_permission(Permission.ENGINE_CONTROL))]

PING_SECONDS = 15
DEFAULT_TICK_SECONDS = 2
STREAM_HEADERS = {"X-Accel-Buffering": "no"}


def _station(value: str) -> Station:
    try:
        return require_station(value)
    except EngineError as exc:
        raise engine_api_error(exc) from exc


# --------------------------------------------------------------------------- reads


@router.get("/engine/status", response_model=EngineStatusOut)
async def get_engine_status(_: ReaderDep, service: EngineServiceDep) -> EngineStatusOut:
    """Per station: state, lag, throughput, in-flight against its limit, dead letters."""
    return EngineStatusOut.from_data(await service.status())


@router.get(
    "/engine/stream",
    response_model=None,
    responses={200: {"model": EngineStatusOut, "content": {"text/event-stream": {}}}},
)
async def stream_engine(
    request: Request, _: ReaderDep, service: EngineServiceDep, config: RuntimeConfigDep
) -> EventSourceResponse:
    """SSE: a ``status`` event on connect and whenever the status changes; a ping every 15 s."""

    async def frames() -> AsyncIterator[dict[str, Any]]:
        last: str | None = None
        counter = 0
        while not await request.is_disconnected():
            tick = DEFAULT_TICK_SECONDS
            try:
                status = EngineStatusOut.from_data(await service.status())
                fingerprint = status.model_dump_json(exclude={"generated_at"})
                if fingerprint != last:
                    last = fingerprint
                    counter += 1
                    yield {"event": "status", "data": status.model_dump_json(), "id": str(counter)}
                tick = await config.get(ck.ENGINE_STREAM_TICK_SECONDS)
            except Exception as exc:
                logger.warning("engine stream tick failed: error=%s", type(exc).__name__)
            await asyncio.sleep(tick)

    return EventSourceResponse(frames(), ping=PING_SECONDS, headers=STREAM_HEADERS)


@router.get("/engine/dead-letters", response_model=DeadLetterPage)
async def list_dead_letters(
    _: ReaderDep,
    service: EngineServiceDep,
    station: Annotated[str | None, Query(description="Only this station's dead letters.")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DeadLetterPage:
    page = await service.list_dead_letters(
        _station(station) if station is not None else None, offset, limit
    )
    return DeadLetterPage(
        items=[DeadLetterOut.from_data(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/engine/audit", response_model=EngineAuditPage)
async def list_engine_audit(
    _: ReaderDep,
    service: EngineServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
) -> EngineAuditPage:
    """Who did what to the engine, newest first. The default page size is a setting."""
    page = await service.audit(offset, limit)
    return EngineAuditPage(
        items=[EngineAuditOut.from_data(item) for item in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


# --------------------------------------------------------------------------- control


@router.post("/engine/stations/{station}/pause", response_model=EngineActionOut)
async def pause_station(
    station: str, body: EngineActionIn, principal: ControllerDep, service: EngineServiceDep
) -> EngineActionOut:
    """Pause a station: in-flight work finishes; new deliveries stay uncommitted on the bus."""
    try:
        result = await service.pause(
            _station(station), body.reason, body.expected_version, principal
        )
    except (EngineError, ConfigError) as exc:
        raise engine_api_error(exc) from exc
    return EngineActionOut.from_data(result)


@router.post("/engine/stations/{station}/resume", response_model=EngineActionOut)
async def resume_station(
    station: str, body: EngineActionIn, principal: ControllerDep, service: EngineServiceDep
) -> EngineActionOut:
    """Resume a paused or drained station."""
    try:
        result = await service.resume(
            _station(station), body.reason, body.expected_version, principal
        )
    except (EngineError, ConfigError) as exc:
        raise engine_api_error(exc) from exc
    return EngineActionOut.from_data(result)


@router.post("/engine/stations/{station}/drain", response_model=EngineActionOut)
async def drain_station(
    station: str, body: EngineActionIn, principal: ControllerDep, service: EngineServiceDep
) -> EngineActionOut:
    """Pause a station and report DRAINED once nothing is in flight."""
    try:
        result = await service.drain(
            _station(station), body.reason, body.expected_version, principal
        )
    except (EngineError, ConfigError) as exc:
        raise engine_api_error(exc) from exc
    return EngineActionOut.from_data(result)


@router.put("/engine/throttle", response_model=EngineActionOut)
async def put_throttle(
    body: ThrottleIn, principal: ControllerDep, service: EngineServiceDep
) -> EngineActionOut:
    """Set items per stage (1 to 32) and Fusion applies per receipt (1 to 8)."""
    try:
        result = await service.set_throttle(
            body.per_stage,
            body.apply_per_receipt,
            body.reason,
            body.expected_version,
            principal,
        )
    except (EngineError, ConfigError) as exc:
        raise engine_api_error(exc) from exc
    return EngineActionOut.from_data(result)


@router.post("/engine/dead-letters/replay", response_model=ReplayOut)
async def replay_dead_letters(
    body: ReplayIn, principal: ControllerDep, service: EngineServiceDep
) -> ReplayOut:
    """Send chosen dead letters back to their stage; locked, done and repeated ones are skipped."""
    event_ids: list[UUID] = body.event_ids
    try:
        result = await service.replay_dead_letters(event_ids, body.reason, principal)
    except (EngineError, ConfigError) as exc:
        raise engine_api_error(exc) from exc
    return ReplayOut.from_data(result)
