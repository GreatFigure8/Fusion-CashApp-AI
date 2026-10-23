"""Runtime configuration endpoints: list, change history, and audited update."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.config_deps import RuntimeConfigDep, change_page, config_api_error
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.schemas.config import ConfigChangePage, ConfigEntry, ConfigUpdate
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.config import (
    ConfigAudit,
    ConfigError,
    ConfigWriter,
    list_config_entries,
    lookup_key,
)

router = APIRouter(tags=["config"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]
WriterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]


@router.get("/config", response_model=list[ConfigEntry])
async def list_config(_: ReaderDep, uow_factory: UowFactoryDep) -> list[ConfigEntry]:
    async with uow_factory() as uow:
        entries = await list_config_entries(uow)
    return [ConfigEntry.model_validate(e, from_attributes=True) for e in entries]


@router.get("/config/{key}/history", response_model=ConfigChangePage)
async def config_history(
    key: str,
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConfigChangePage:
    try:
        lookup_key(key)
    except ConfigError as exc:
        raise config_api_error(exc) from exc
    async with uow_factory() as uow:
        page = await ConfigAudit.history(uow, key, offset=offset, limit=limit)
    return change_page(page)


@router.put("/config/{key}", response_model=ConfigEntry)
async def put_config(
    key: str,
    body: ConfigUpdate,
    principal: WriterDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
) -> ConfigEntry:
    try:
        async with uow_factory() as uow:
            await ConfigWriter().set(
                uow, key, body.value, principal, body.reason, body.expected_version
            )
            entry = (await list_config_entries(uow, only=key))[0]
            await uow.commit()
    except ConfigError as exc:
        raise config_api_error(exc) from exc
    runtime.invalidate()
    return ConfigEntry.model_validate(entry, from_attributes=True)
