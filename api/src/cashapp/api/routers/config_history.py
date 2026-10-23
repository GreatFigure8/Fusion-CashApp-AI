"""Cross-key configuration change history (feeds the Settings "Change history" card)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.config_deps import change_page
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.schemas.config import ConfigChangePage
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.config import ConfigAudit

router = APIRouter(tags=["config"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]


@router.get("/config/history", response_model=ConfigChangePage)
async def config_history_all(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConfigChangePage:
    async with uow_factory() as uow:
        page = await ConfigAudit.history_all(uow, offset=offset, limit=limit)
    return change_page(page)
