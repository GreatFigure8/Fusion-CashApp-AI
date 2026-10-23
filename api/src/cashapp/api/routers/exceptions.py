"""The exception workbench: the worklist, and the Fusion context of one item. Read-only."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.api.schemas.exceptions import (
    ExceptionListOut,
    ExceptionListQuery,
    FusionContextOut,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import build_fusion_client
from cashapp.integrations.fusion.guard import read_only
from cashapp.services.exceptions_query import ExceptionsQueryService
from cashapp.services.fusion_context import FusionContextCache, FusionContextService
from cashapp.services.locking import ItemNotFound
from cashapp.services.runtime_settings import RuntimeSettings

router = APIRouter(tags=["exceptions"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]

_context_cache = FusionContextCache()
"""One cache per process; every API instance keeps its own 60 second view."""


@lru_cache
def _reader_for(runtime: RuntimeSettings) -> FusionClient:
    return read_only(build_fusion_client(runtime))


def get_fusion_reader(runtime: RuntimeSettingsDep) -> FusionClient:
    """A read-only Fusion client, built on first use. These endpoints never write to Fusion."""
    return _reader_for(runtime)


def get_exceptions_service(runtime: RuntimeConfigDep) -> ExceptionsQueryService:
    """The worklist service; tests override this dependency."""
    return ExceptionsQueryService(runtime)


def get_fusion_context_service(
    fusion: Annotated[FusionClient, Depends(get_fusion_reader)],
) -> FusionContextService:
    """The Fusion context service; tests override this dependency."""
    return FusionContextService(fusion, cache=_context_cache)


ExceptionsServiceDep = Annotated[ExceptionsQueryService, Depends(get_exceptions_service)]
FusionContextServiceDep = Annotated[FusionContextService, Depends(get_fusion_context_service)]


@router.get("/exceptions", response_model=ExceptionListOut)
async def list_exceptions(
    query: Annotated[ExceptionListQuery, Query()],
    principal: ReaderDep,
    uow_factory: UowFactoryDep,
    service: ExceptionsServiceDep,
) -> ExceptionListOut:
    async with uow_factory() as uow:
        page = await service.list(uow, query.to_filters(), principal)
    return ExceptionListOut.from_page(page, number=query.page, page_size=query.page_size)


@router.get("/items/{item_id}/fusion-context", response_model=FusionContextOut)
async def get_fusion_context(
    item_id: int,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    service: FusionContextServiceDep,
) -> FusionContextOut:
    try:
        async with uow_factory() as uow:
            context = await service.build(uow, item_id)
    except ItemNotFound as exc:
        raise ApiError(404, "item_not_found", f"Item {exc.item_id} not found") from exc
    return FusionContextOut.from_context(context)
