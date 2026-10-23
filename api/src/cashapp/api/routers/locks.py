"""Item lock endpoints: acquire, renew, release, force-take, and read."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm.exc import StaleDataError

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.schemas.locks import ForceTakeIn, LockInfoOut, lock_error_to_api
from cashapp.auth.deps import require_permission
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.principal import Permission, Principal
from cashapp.services.locking import LockError, LockInfo, LockService

router = APIRouter(tags=["locks"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]
WorkerDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_WORK))]


def get_lock_service(runtime: RuntimeConfigDep) -> LockService:
    """The lock service; tests override this dependency."""
    return LockService(runtime)


LockServiceDep = Annotated[LockService, Depends(get_lock_service)]


async def _stale_conflict(uow_factory: UowFactory, service: LockService, item_id: int) -> ApiError:
    """A concurrent writer won: re-read the row and report who holds it."""
    async with uow_factory() as uow:
        try:
            info = await service.get(uow, item_id)
        except LockError as exc:
            return lock_error_to_api(exc)
    if info is None:
        return ApiError(409, "lock_conflict", "The lock changed, try again")
    return ApiError(
        409,
        "lock_conflict",
        f"Locked by {info.owner_name}",
        details=[{"owner_name": info.owner_name, "acquired_at": info.acquired_at.isoformat()}],
    )


async def _execute[T](
    uow_factory: UowFactory,
    service: LockService,
    item_id: int,
    action: Callable[[UnitOfWork], Awaitable[T]],
) -> T:
    """Run one lock action in its own transaction, committing on success."""
    try:
        async with uow_factory() as uow:
            result = await action(uow)
            await uow.commit()
            return result
    except LockError as exc:
        raise lock_error_to_api(exc) from exc
    except StaleDataError as exc:
        raise await _stale_conflict(uow_factory, service, item_id) from exc


def _out(info: LockInfo) -> LockInfoOut:
    return LockInfoOut(
        item_id=info.item_id,
        owner=info.owner,
        owner_name=info.owner_name,
        acquired_at=info.acquired_at,
        expires_at=info.expires_at,
    )


@router.get("/items/{item_id}/lock", response_model=LockInfoOut | None)
async def get_lock(
    item_id: int, _: ReaderDep, uow_factory: UowFactoryDep, service: LockServiceDep
) -> LockInfoOut | None:
    try:
        async with uow_factory() as uow:
            return LockInfoOut.from_info(await service.get(uow, item_id))
    except LockError as exc:
        raise lock_error_to_api(exc) from exc


@router.post("/items/{item_id}/lock", response_model=LockInfoOut)
async def acquire_lock(
    item_id: int, principal: WorkerDep, uow_factory: UowFactoryDep, service: LockServiceDep
) -> LockInfoOut:
    info = await _execute(
        uow_factory, service, item_id, lambda uow: service.acquire(uow, item_id, principal)
    )
    return _out(info)


@router.post("/items/{item_id}/lock/renew", response_model=LockInfoOut)
async def renew_lock(
    item_id: int, principal: WorkerDep, uow_factory: UowFactoryDep, service: LockServiceDep
) -> LockInfoOut:
    info = await _execute(
        uow_factory, service, item_id, lambda uow: service.renew(uow, item_id, principal)
    )
    return _out(info)


@router.delete("/items/{item_id}/lock", status_code=204, response_class=Response)
async def release_lock(
    item_id: int, principal: WorkerDep, uow_factory: UowFactoryDep, service: LockServiceDep
) -> Response:
    await _execute(
        uow_factory, service, item_id, lambda uow: service.release(uow, item_id, principal)
    )
    return Response(status_code=204)


@router.post("/items/{item_id}/lock/force", response_model=LockInfoOut)
async def force_take_lock(
    item_id: int,
    body: ForceTakeIn,
    principal: WorkerDep,
    uow_factory: UowFactoryDep,
    service: LockServiceDep,
) -> LockInfoOut:
    info = await _execute(
        uow_factory,
        service,
        item_id,
        lambda uow: service.force_take(uow, item_id, principal, body.reason),
    )
    return _out(info)
