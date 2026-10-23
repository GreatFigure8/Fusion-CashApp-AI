"""Backlog reprocessing: start, watch and steer batches of historical remittances."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.storage_deps import ObjectStoreDep
from cashapp.auth.deps import require_permission
from cashapp.data.uow import UowFactory
from cashapp.domain.backlog import (
    BATCH_NAME_PATTERN,
    BacklogSourceKind,
    BacklogStatus,
    BatchProgress,
)
from cashapp.domain.clock import SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.integrations.folder import FolderSource
from cashapp.services.backlog.service import (
    BacklogError,
    BacklogResumeViaCli,
    BacklogService,
    backlog_error_to_api,
)
from cashapp.services.backlog.sources import resolve_backlog_folder, resolve_stored_folder
from cashapp.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backlog", tags=["backlog"], responses=ERROR_RESPONSES)

RunnerDep = Annotated[Principal, Depends(require_permission(Permission.BACKLOG_RUN))]
ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]

_MAX_RATE = 10_000
_MAX_LIMIT = 200


class BacklogBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=BATCH_NAME_PATTERN)
    folder: str = Field(min_length=1, max_length=500)
    dry_run: bool = False
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=_MAX_RATE)


class BacklogPromote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=BATCH_NAME_PATTERN)
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=_MAX_RATE)


class BacklogBatchOut(BaseModel):
    id: int
    name: str
    status: BacklogStatus
    dry_run: bool
    source_kind: BacklogSourceKind
    total: int
    processed: int
    applied: int
    escalated: int
    failed: int
    awaiting: int
    in_flight: int
    rate_limit_per_minute: int
    eta_minutes: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: str
    promoted_from_id: int | None
    import_error: str | None

    @classmethod
    def from_progress(cls, progress: BatchProgress) -> "BacklogBatchOut":
        return cls(
            id=progress.id,
            name=progress.name,
            status=progress.status,
            dry_run=progress.dry_run,
            source_kind=progress.source_kind,
            total=progress.total,
            processed=progress.processed,
            applied=progress.applied,
            escalated=progress.escalated,
            failed=progress.failed,
            awaiting=progress.awaiting,
            in_flight=progress.in_flight,
            rate_limit_per_minute=progress.rate_limit_per_minute,
            eta_minutes=progress.eta_minutes,
            started_at=progress.started_at,
            finished_at=progress.finished_at,
            created_by=progress.created_by,
            promoted_from_id=progress.promoted_from_id,
            import_error=progress.import_error,
        )


def get_backlog_service(object_store: ObjectStoreDep, config: RuntimeConfigDep) -> BacklogService:
    return BacklogService(object_store=object_store, config=config)


ServiceDep = Annotated[BacklogService, Depends(get_backlog_service)]


async def _progress_of(
    service: BacklogService, uow_factory: UowFactory, batch_id: int
) -> BacklogBatchOut:
    async with uow_factory() as uow:
        rows = await service.progress(uow, batch_id=batch_id)
    return BacklogBatchOut.from_progress(rows[0])


async def _import_in_background(
    service: BacklogService, uow_factory: UowFactory, batch_id: int, folder: Path
) -> None:
    """Runs after the response. ``run_import`` records its own failure on the batch."""
    try:
        await service.run_import(uow_factory, batch_id, FolderSource(folder, clock=SystemClock()))
    except Exception as exc:
        logger.error("backlog background import failed: error=%s", type(exc).__name__)


@router.post("/batches", status_code=202, response_model=BacklogBatchOut)
async def create_batch(
    body: BacklogBatchCreate,
    background: BackgroundTasks,
    principal: RunnerDep,
    service: ServiceDep,
    uow_factory: UowFactoryDep,
) -> BacklogBatchOut:
    try:
        folder = resolve_backlog_folder(get_settings(), body.folder)
        batch = await service.create_batch(
            uow_factory,
            name=body.name,
            dry_run=body.dry_run,
            rate_limit=body.rate_limit_per_minute,
            source_kind=BacklogSourceKind.FOLDER,
            source_ref=str(folder),
            principal=principal,
        )
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc
    background.add_task(_import_in_background, service, uow_factory, batch.id, folder)
    return await _progress_of(service, uow_factory, batch.id)


@router.get("/batches", response_model=list[BacklogBatchOut])
async def list_batches(
    _: ReaderDep,
    service: ServiceDep,
    uow_factory: UowFactoryDep,
    status: Annotated[list[BacklogStatus] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = 100,
) -> list[BacklogBatchOut]:
    async with uow_factory() as uow:
        rows = await service.progress(uow, statuses=status, limit=limit)
    return [BacklogBatchOut.from_progress(row) for row in rows]


@router.get("/batches/{batch_id}", response_model=BacklogBatchOut)
async def get_batch(
    batch_id: int, _: ReaderDep, service: ServiceDep, uow_factory: UowFactoryDep
) -> BacklogBatchOut:
    try:
        return await _progress_of(service, uow_factory, batch_id)
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc


@router.post("/batches/{batch_id}/pause", response_model=BacklogBatchOut)
async def pause_batch(
    batch_id: int, principal: RunnerDep, service: ServiceDep, uow_factory: UowFactoryDep
) -> BacklogBatchOut:
    try:
        await service.pause(uow_factory, batch_id, principal=principal)
        return await _progress_of(service, uow_factory, batch_id)
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc


@router.post("/batches/{batch_id}/resume", response_model=BacklogBatchOut)
async def resume_batch(
    batch_id: int,
    background: BackgroundTasks,
    principal: RunnerDep,
    service: ServiceDep,
    uow_factory: UowFactoryDep,
) -> BacklogBatchOut:
    try:
        await service.resume(uow_factory, batch_id, principal=principal, can_import_mailbox=False)
        progress = await _progress_of(service, uow_factory, batch_id)
        if progress.status == BacklogStatus.IMPORTING:
            if progress.source_kind != BacklogSourceKind.FOLDER:
                raise BacklogResumeViaCli(batch_id)
            folder = await _stored_folder(service, uow_factory, batch_id)
            background.add_task(_import_in_background, service, uow_factory, batch_id, folder)
        return progress
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc


async def _stored_folder(service: BacklogService, uow_factory: UowFactory, batch_id: int) -> Path:
    source_ref = await service.source_ref(uow_factory, batch_id)
    return resolve_stored_folder(get_settings(), source_ref)


@router.post("/batches/{batch_id}/cancel", response_model=BacklogBatchOut)
async def cancel_batch(
    batch_id: int, principal: RunnerDep, service: ServiceDep, uow_factory: UowFactoryDep
) -> BacklogBatchOut:
    try:
        await service.cancel(uow_factory, batch_id, principal=principal)
        return await _progress_of(service, uow_factory, batch_id)
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc


@router.post("/batches/{batch_id}/promote", status_code=201, response_model=BacklogBatchOut)
async def promote_batch(
    batch_id: int,
    body: BacklogPromote,
    principal: RunnerDep,
    service: ServiceDep,
    uow_factory: UowFactoryDep,
) -> BacklogBatchOut:
    try:
        batch = await service.promote(
            uow_factory,
            batch_id,
            name=body.name,
            rate_limit=body.rate_limit_per_minute,
            principal=principal,
        )
        return await _progress_of(service, uow_factory, batch.id)
    except BacklogError as exc:
        raise backlog_error_to_api(exc) from exc
