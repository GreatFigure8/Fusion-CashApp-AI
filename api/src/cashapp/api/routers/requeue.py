"""Human requeue endpoint: fix the data, then send the item back down the assembly line."""

import importlib
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm.exc import StaleDataError

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.schemas.locks import lock_error_to_api
from cashapp.api.schemas.requeue import RequeueIn, RequeueOut, requeue_error_to_api
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.autofix.requeue import RequeueCommand, RequeueError, RequeueService
from cashapp.services.locking import LockError, LockService

router = APIRouter(tags=["requeue"], responses=ERROR_RESPONSES)

WorkerDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_WORK))]


def get_requeue_service(runtime: RuntimeConfigDep) -> RequeueService:
    """The requeue service; tests override this dependency."""
    return RequeueService(lock_service=LockService(runtime))


RequeueServiceDep = Annotated[RequeueService, Depends(get_requeue_service)]


def _alias_error(exc: Exception) -> ApiError | None:
    """Map a payer-alias error (s37) to the error shape, or None when it is not one."""
    try:
        error_type = getattr(
            importlib.import_module("cashapp.services.aliases"), "AliasError", None
        )
    except ModuleNotFoundError:
        return None
    if isinstance(error_type, type) and isinstance(exc, error_type):
        mapper = importlib.import_module("cashapp.api.schemas.aliases").alias_error_to_api
        mapped = mapper(exc)
        return mapped if isinstance(mapped, ApiError) else None
    return None


@router.post("/items/{item_id}/requeue", response_model=RequeueOut)
async def requeue_item(
    item_id: int,
    body: RequeueIn,
    principal: WorkerDep,
    uow_factory: UowFactoryDep,
    service: RequeueServiceDep,
) -> RequeueOut:
    command = RequeueCommand(
        note=body.note,
        target_stage=body.target_stage,
        corrected_extraction=body.corrected_extraction,
        customer_number=body.customer_number,
        receipt_id=body.receipt_id,
        learn_alias=body.learn_alias,
    )
    try:
        async with uow_factory() as uow:
            result = await service.requeue(uow, item_id, command, principal)
            await uow.commit()
    except LockError as exc:
        raise lock_error_to_api(exc) from exc
    except RequeueError as exc:
        raise requeue_error_to_api(exc) from exc
    except StaleDataError as exc:
        raise ApiError(409, "item_changed", "The item changed, reload and try again") from exc
    except Exception as exc:
        mapped = _alias_error(exc)
        if mapped is None:
            raise
        raise mapped from exc
    return RequeueOut.from_result(result)
