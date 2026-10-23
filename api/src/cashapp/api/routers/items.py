"""The item view: detail, history, the stored artifact parts, and search for the command palette."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import StringConstraints

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.routers.flow import ClockDep
from cashapp.api.schemas.items import HistoryOut, ItemDetailOut, SearchHitOut, SearchOut
from cashapp.api.storage_deps import ObjectStoreDep
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.flow_query import (
    ItemNotFound,
    PartNotFound,
    PartPurged,
    item_detail,
    item_history,
    open_part,
    search_items,
)

router = APIRouter(tags=["items"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]

HISTORY_PAGE_SIZE = 200
SEARCH_LIMIT = 10


def _not_found(exc: ItemNotFound) -> ApiError:
    return ApiError(404, "item_not_found", f"Item {exc.item_id} not found")


@router.get("/items/{item_id}", response_model=ItemDetailOut)
async def get_item(
    item_id: int, _: ReaderDep, uow_factory: UowFactoryDep, clock: ClockDep
) -> ItemDetailOut:
    try:
        async with uow_factory() as uow:
            data = await item_detail(uow, item_id, now=clock.now())
    except ItemNotFound as exc:
        raise _not_found(exc) from exc
    return ItemDetailOut.from_data(data)


@router.get("/items/{item_id}/history", response_model=HistoryOut)
async def get_item_history(
    item_id: int,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    page: Annotated[int, Query(ge=1)] = 1,
) -> HistoryOut:
    try:
        async with uow_factory() as uow:
            result = await item_history(uow, item_id, page=page, page_size=HISTORY_PAGE_SIZE)
    except ItemNotFound as exc:
        raise _not_found(exc) from exc
    return HistoryOut.from_rows(result.items, total=result.total)


@router.get(
    "/items/{item_id}/parts/{part_no}",
    response_class=Response,
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "The part's bytes."}
    },
)
async def get_item_part(
    item_id: int,
    part_no: int,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    store: ObjectStoreDep,
    variant: Literal["original", "text"] = "original",
) -> Response:
    """Stream one stored part inline. Neither the bytes nor the object key are ever logged."""
    try:
        async with uow_factory() as uow:
            content = await open_part(uow, store, item_id, part_no, variant=variant)
    except PartNotFound as exc:
        code = "part_text_not_found" if exc.text else "part_not_found"
        raise ApiError(404, code, "That part was not found") from exc
    except PartPurged as exc:
        raise ApiError(
            410, "artifact_purged", "This artifact was purged under the retention policy"
        ) from exc
    return Response(
        content=content.data,
        media_type=content.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{content.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/search", response_model=SearchOut)
async def search(
    q: Annotated[
        str, Query(), StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ],
    _: ReaderDep,
    uow_factory: UowFactoryDep,
) -> SearchOut:
    async with uow_factory() as uow:
        hits = await search_items(uow, q, limit=SEARCH_LIMIT)
    return SearchOut(hits=[SearchHitOut.from_hit(hit) for hit in hits])
