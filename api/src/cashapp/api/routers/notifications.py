"""The notification log: what was sent, failed or suppressed."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.schemas.notifications import NotificationLogPage
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.notifications.log_query import NotificationLogService

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=ERROR_RESPONSES)

ReportsDep = Annotated[Principal, Depends(require_permission(Permission.REPORTS_READ))]


@router.get("/log", response_model=NotificationLogPage)
async def get_notification_log(
    _: ReportsDep,
    uow_factory: UowFactoryDep,
    kind: str | None = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> NotificationLogPage:
    if from_ is not None and to is not None and from_ > to:
        raise ApiError(422, "invalid_range", "'from' must not be after 'to'")
    async with uow_factory() as uow:
        page = await NotificationLogService().list_log(
            uow, kind=kind, from_=from_, to=to, offset=offset, limit=limit
        )
    return NotificationLogPage.of(page)
