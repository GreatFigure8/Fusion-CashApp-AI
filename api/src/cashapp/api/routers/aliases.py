"""Payer alias endpoints: list, and retire a wrong alias."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.schemas.aliases import AliasOut, AliasPage, RetireAliasIn, alias_error_to_api
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.aliases import AliasError, AliasService

router = APIRouter(tags=["aliases"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]
WriterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]


@router.get("/aliases", response_model=AliasPage)
async def list_aliases(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    active: bool = True,
    q: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AliasPage:
    async with uow_factory() as uow:
        page = await AliasService(uow).search(uow, active=active, q=q, offset=offset, limit=limit)
        return AliasPage(
            items=[AliasOut.from_model(alias) for alias in page.items],
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )


@router.post("/aliases/{alias_id}/retire", response_model=AliasOut)
async def retire_alias(
    alias_id: int, body: RetireAliasIn, principal: WriterDep, uow_factory: UowFactoryDep
) -> AliasOut:
    try:
        async with uow_factory() as uow:
            alias = await AliasService(uow).retire(uow, alias_id, principal, body.reason)
            out = AliasOut.from_model(alias)
            await uow.commit()
            return out
    except AliasError as exc:
        raise alias_error_to_api(exc) from exc
