"""The Review board: upload failed receipts for in-depth review, the queue, quota and results."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.datastructures import UploadFile

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.routers.flow import ClockDep
from cashapp.api.schemas.review import (
    QuotaOut,
    ReviewQueuePage,
    ReviewQueueRowOut,
    ReviewResultOut,
    StagedUploadsOut,
    UploadLimitsOut,
    UploadResultOut,
)
from cashapp.api.storage_deps import ObjectStoreDep
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.review.queue import ReviewQueueService, ReviewResultService
from cashapp.services.review.upload import UploadService

router = APIRouter(prefix="/review", tags=["review"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]
WorkerDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_WORK))]

MAX_QUEUE_PAGE = 100
_ENVELOPE_ALLOWANCE = 1024 * 1024  # multipart framing and the small form fields
_FORM_FIELDS = 4


def get_upload_service(
    uow_factory: UowFactoryDep,
    store: ObjectStoreDep,
    runtime: RuntimeConfigDep,
    clock: ClockDep,
) -> UploadService:
    """The upload service; tests override this dependency."""
    return UploadService(uow_factory, store, runtime, clock)


UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


async def _read_files(request: Request, runtime: RuntimeConfigDep) -> list[UploadFile]:
    """The ``files`` parts of a bounded multipart request; refuses anything else."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise ApiError(415, "unsupported_media_type", "Send the files as multipart/form-data")
    cfg = await runtime.uploads()
    declared = request.headers.get("content-length")
    if declared is None:
        raise ApiError(411, "length_required", "A Content-Length header is required")
    limit = cfg.max_files_per_request * cfg.max_file_bytes + _ENVELOPE_ALLOWANCE
    try:
        too_big = int(declared) > limit
    except ValueError as exc:
        raise ApiError(400, "bad_request", "Invalid Content-Length") from exc
    if too_big:
        raise ApiError(413, "payload_too_large", "The upload is larger than the limit allows")
    form = await request.form(max_files=cfg.max_files_per_request + 1, max_fields=_FORM_FIELDS)
    return [part for part in form.getlist("files") if isinstance(part, UploadFile)]


@router.post("/uploads", response_model=UploadResultOut | StagedUploadsOut)
async def upload_files(
    request: Request,
    principal: WorkerDep,
    service: UploadServiceDep,
    runtime: RuntimeConfigDep,
    stage_only: Annotated[bool, Query()] = False,
) -> UploadResultOut | StagedUploadsOut:
    """Submit files for in-depth review, or only stage them for a chat message (``stage_only``)."""
    files = await _read_files(request, runtime)
    if not files:
        raise ApiError(422, "no_files", "Attach at least one file in the 'files' field")
    try:
        if stage_only:
            return StagedUploadsOut.from_batch(await service.stage(files, principal))
        return UploadResultOut.from_batch(await service.submit(files, principal))
    finally:
        for part in files:
            await part.close()


@router.get("/queue", response_model=ReviewQueuePage)
async def review_queue(
    _: ReaderDep,
    uow_factory: UowFactoryDep,
    clock: ClockDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_QUEUE_PAGE)] = 20,
    open_only: bool = False,
) -> ReviewQueuePage:
    async with uow_factory() as uow:
        page = await ReviewQueueService(clock).page(uow, offset, limit, open_only)
    return ReviewQueuePage(
        items=[ReviewQueueRowOut.from_row(row) for row in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


@router.get("/quota", response_model=QuotaOut)
async def review_quota(principal: ReaderDep, service: UploadServiceDep) -> QuotaOut:
    return QuotaOut.from_quota(await service.quota(principal))


@router.get("/limits", response_model=UploadLimitsOut)
async def review_limits(_: ReaderDep, runtime: RuntimeConfigDep) -> UploadLimitsOut:
    cfg = await runtime.uploads()
    return UploadLimitsOut(
        max_file_bytes=cfg.max_file_bytes,
        max_files_per_request=cfg.max_files_per_request,
        allowed_types=list(cfg.allowed_types),
    )


@router.get("/items/{item_id}/result", response_model=ReviewResultOut)
async def review_result(item_id: int, _: ReaderDep, uow_factory: UowFactoryDep) -> ReviewResultOut:
    async with uow_factory() as uow:
        result = await ReviewResultService().result(uow, item_id)
    if result is None:
        raise ApiError(404, "item_not_found", f"Item {item_id} not found")
    return ReviewResultOut.from_result(result)
