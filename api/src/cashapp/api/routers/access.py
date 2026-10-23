"""Group-to-role mapping endpoints (the table is owned by sign-in; changes are audited here)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.config_deps import change_page, config_api_error
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.schemas.config import (
    ConfigChangePage,
    GroupRoleMappingModel,
    GroupRolesResponse,
    GroupRolesUpdate,
)
from cashapp.auth.deps import require_permission
from cashapp.data.repositories.config import ConfigChangeRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.principal import Permission, Principal
from cashapp.services.config import ConfigAudit, ConfigError
from cashapp.services.group_roles import GROUP_ROLE_AUDIT_KEY, GroupRoleInput, GroupRoleService

router = APIRouter(tags=["access"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]
WriterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]


async def _response(uow: UnitOfWork) -> GroupRolesResponse:
    mappings = await GroupRoleService().current(uow)
    latest = await uow.repo(ConfigChangeRepository).latest_by_key([GROUP_ROLE_AUDIT_KEY])
    change = latest.get(GROUP_ROLE_AUDIT_KEY)
    return GroupRolesResponse(
        mappings=[GroupRoleMappingModel(group_name=m.group_name, role=m.role) for m in mappings],
        updated_by=change.changed_by if change is not None else None,
        updated_at=change.changed_at if change is not None else None,
    )


@router.get("/access/group-roles", response_model=GroupRolesResponse)
async def get_group_roles(_: ReaderDep, uow_factory: UowFactoryDep) -> GroupRolesResponse:
    async with uow_factory() as uow:
        return await _response(uow)


@router.put("/access/group-roles", response_model=GroupRolesResponse)
async def put_group_roles(
    body: GroupRolesUpdate,
    principal: WriterDep,
    uow_factory: UowFactoryDep,
) -> GroupRolesResponse:
    try:
        async with uow_factory() as uow:
            await GroupRoleService().replace(
                uow,
                [GroupRoleInput(m.group_name, m.role) for m in body.mappings],
                principal,
                body.reason,
            )
            response = await _response(uow)
            await uow.commit()
    except ConfigError as exc:
        raise config_api_error(exc) from exc
    return response


@router.get("/access/group-roles/history", response_model=ConfigChangePage)
async def group_roles_history(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConfigChangePage:
    async with uow_factory() as uow:
        page = await ConfigAudit.history(uow, GROUP_ROLE_AUDIT_KEY, offset=offset, limit=limit)
    return change_page(page)
