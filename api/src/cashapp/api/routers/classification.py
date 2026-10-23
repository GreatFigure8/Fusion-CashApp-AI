"""Classification endpoints: a person's override, and the decision trail of an item."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm.exc import StaleDataError

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.schemas.classification import (
    ClassificationOut,
    ClassificationOverrideIn,
    ClassificationOverrideOut,
    classification_error_to_api,
)
from cashapp.api.schemas.locks import lock_error_to_api
from cashapp.auth.deps import require_permission
from cashapp.data.repositories.classification import ClassificationRepository
from cashapp.domain.principal import Permission, Principal
from cashapp.services.classification import (
    ClassificationForbidden,
    ClassificationOverrideService,
    InvalidClassificationState,
)
from cashapp.services.locking import LockError

router = APIRouter(tags=["classification"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.ITEMS_READ))]
OverriderDep = Annotated[Principal, Depends(require_permission(Permission.CLASSIFICATION_OVERRIDE))]


def get_classification_service() -> ClassificationOverrideService:
    """The override service; tests override this dependency."""
    return ClassificationOverrideService()


ServiceDep = Annotated[ClassificationOverrideService, Depends(get_classification_service)]


@router.post(
    "/items/{item_id}/classification/override",
    response_model=ClassificationOverrideOut,
    operation_id="override_classification",
)
async def override_classification(
    item_id: int,
    body: ClassificationOverrideIn,
    principal: OverriderDep,
    uow_factory: UowFactoryDep,
    service: ServiceDep,
) -> ClassificationOverrideOut:
    try:
        async with uow_factory() as uow:
            result = await service.override(
                uow, item_id, principal, is_remittance=body.is_remittance, reason=body.reason
            )
            out = ClassificationOverrideOut(
                classification=ClassificationOut.from_row(result.classification),
                stage=result.stage,
                state=result.state,
            )
            await uow.commit()
            return out
    except LockError as exc:
        raise lock_error_to_api(exc) from exc
    except (InvalidClassificationState, ClassificationForbidden) as exc:
        raise classification_error_to_api(exc) from exc
    except StaleDataError as exc:
        raise ApiError(409, "item_busy", "The item changed while overriding, try again") from exc


@router.get(
    "/items/{item_id}/classifications",
    response_model=list[ClassificationOut],
    operation_id="list_classifications",
)
async def list_classifications(
    item_id: int, _: ReaderDep, uow_factory: UowFactoryDep
) -> list[ClassificationOut]:
    async with uow_factory() as uow:
        if await uow.work_items.get(item_id) is None:
            raise ApiError(404, "item_not_found", f"Item {item_id} not found")
        rows = await uow.repo(ClassificationRepository).for_item(item_id)
        return [ClassificationOut.from_row(row) for row in rows]
