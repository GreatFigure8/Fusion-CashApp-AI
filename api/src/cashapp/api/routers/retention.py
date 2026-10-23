"""Retention purge endpoint: an admin runs (or previews) a purge on demand."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.storage_deps import ObjectStoreDep
from cashapp.auth.deps import require_permission
from cashapp.domain.clock import SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.services.retention.service import RetentionService

router = APIRouter(prefix="/admin/retention", tags=["retention"], responses=ERROR_RESPONSES)

AdminDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]

_REQUEST_LIMIT = 500


class PurgeRequest(BaseModel):
    """``dry_run`` has no default on purpose: an empty POST must never purge."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool


class PurgeReportResponse(BaseModel):
    dry_run: bool
    ran_at: datetime
    artifacts: int
    parts: int
    readings: int
    adjudications: int
    history_payloads: int
    objects_deleted: int
    objects_kept_shared: int
    resumed: int
    skipped: int


@router.post("/purge", response_model=PurgeReportResponse)
async def purge(
    body: PurgeRequest,
    principal: AdminDep,
    runtime: RuntimeConfigDep,
    uow_factory: UowFactoryDep,
    object_store: ObjectStoreDep,
) -> PurgeReportResponse:
    service = RetentionService(await runtime.retention())
    report = await service.purge(
        uow_factory,
        object_store,
        SystemClock().now(),
        dry_run=body.dry_run,
        limit=_REQUEST_LIMIT,
        principal=principal,
    )
    await RetentionService.record_run(uow_factory, report, principal)
    return PurgeReportResponse(
        dry_run=report.dry_run,
        ran_at=report.ran_at,
        artifacts=report.artifacts,
        parts=report.parts,
        readings=report.readings,
        adjudications=report.adjudications,
        history_payloads=report.history_payloads,
        objects_deleted=report.objects_deleted,
        objects_kept_shared=report.objects_kept_shared,
        resumed=report.resumed,
        skipped=report.skipped,
    )
