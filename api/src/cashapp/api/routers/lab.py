"""The matching lab: propose a candidate, replay it against past items, promote or discard.

A replay is a background task in this API process, started by the POST. Its progress streams
over SSE for as long as a client holds the connection; nothing here polls an external source.
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sse_starlette import EventSourceResponse

from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.lab_deps import LabServiceDep, lab_api_error
from cashapp.api.schemas.lab import (
    CandidateCreateIn,
    CandidateListOut,
    CandidateOut,
    DiscardIn,
    PromoteIn,
    PromoteOut,
    ReplayResultOut,
    ReplayStartIn,
    ReplayStartOut,
    ReplayStreamFrameOut,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.lab import CandidateStatus
from cashapp.domain.principal import Permission, Principal
from cashapp.services.lab.errors import LabError
from cashapp.services.lab.service import ProgressEvent

router = APIRouter(prefix="/lab", tags=["lab"], responses=ERROR_RESPONSES)

LabRunnerDep = Annotated[Principal, Depends(require_permission(Permission.LAB_RUN))]
LabPromoterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]

PING_SECONDS = 15
_STREAM_HEADERS = {"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}


@router.post("/candidates", response_model=CandidateOut, status_code=201)
async def create_candidate(
    body: CandidateCreateIn, principal: LabRunnerDep, service: LabServiceDep
) -> CandidateOut:
    try:
        candidate = await service.create_candidate(body.changes, body.rationale, principal)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return CandidateOut.of(candidate)


@router.get("/candidates", response_model=CandidateListOut)
async def list_candidates(
    principal: LabRunnerDep,
    service: LabServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: CandidateStatus | None = None,
) -> CandidateListOut:
    try:
        listing = await service.list_candidates(principal, limit=limit, status=status)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return CandidateListOut.of(listing)


@router.post("/candidates/{candidate_id}/replays", response_model=ReplayStartOut, status_code=202)
async def start_replay(
    candidate_id: str, body: ReplayStartIn, principal: LabRunnerDep, service: LabServiceDep
) -> ReplayStartOut:
    try:
        replay = await service.replay(candidate_id, body.window_days, principal)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return ReplayStartOut.of(replay)


@router.get("/replays/{replay_id}", response_model=ReplayResultOut)
async def get_replay(
    replay_id: str, principal: LabRunnerDep, service: LabServiceDep
) -> ReplayResultOut:
    try:
        result = await service.get_replay(replay_id, principal)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return ReplayResultOut.of(result)


def _frame(event: ProgressEvent, event_id: int) -> dict[str, Any]:
    return {"event": event.kind, "data": json.dumps(event.data), "id": str(event_id)}


@router.get(
    "/replays/{replay_id}/stream",
    response_model=None,
    responses={200: {"model": ReplayStreamFrameOut, "content": {"text/event-stream": {}}}},
)
async def stream_replay(
    replay_id: str, principal: LabRunnerDep, service: LabServiceDep
) -> EventSourceResponse:
    source = service.stream(replay_id, principal)
    try:
        first = await anext(source)  # a bad id or a missing permission fails before streaming
    except LabError as exc:
        raise lab_api_error(exc) from exc
    except StopAsyncIteration:
        first = None

    async def frames() -> AsyncIterator[dict[str, Any]]:
        counter = 0
        try:
            if first is None:
                return
            counter += 1
            yield _frame(first, counter)
            if first.terminal:
                return
            async for event in source:
                counter += 1
                yield _frame(event, counter)
        finally:
            await source.aclose()

    return EventSourceResponse(frames(), ping=PING_SECONDS, headers=_STREAM_HEADERS)


@router.get("/replays/{replay_id}/items.csv", response_model=None)
async def replay_items_csv(
    replay_id: str, principal: LabRunnerDep, service: LabServiceDep
) -> StreamingResponse:
    try:
        lines = await service.items_csv(replay_id, principal)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return StreamingResponse(
        lines,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{replay_id}-items.csv"'},
    )


@router.post("/candidates/{candidate_id}/promote", response_model=PromoteOut)
async def promote_candidate(
    candidate_id: str, body: PromoteIn, principal: LabPromoterDep, service: LabServiceDep
) -> PromoteOut:
    try:
        promotion = await service.promote(
            candidate_id, body.replay_id, body.reason, body.expected_version, principal
        )
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return PromoteOut.of(promotion)


@router.post("/candidates/{candidate_id}/discard", response_model=CandidateOut)
async def discard_candidate(
    candidate_id: str, body: DiscardIn, principal: LabRunnerDep, service: LabServiceDep
) -> CandidateOut:
    try:
        candidate = await service.discard(candidate_id, principal, body.reason)
    except LabError as exc:
        raise lab_api_error(exc) from exc
    return CandidateOut.of(candidate)
