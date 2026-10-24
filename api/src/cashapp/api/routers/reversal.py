"""Reverse an automated application (workbench action, permission ``apply:reverse``)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES
from cashapp.api.fusion_deps import FusionClientDep
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.api.schemas.reversal import ReverseIn, ReverseOut, reversal_error_to_api
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.reversal import ReversalError, ReversalService

router = APIRouter(tags=["reversal"], responses=ERROR_RESPONSES)

ReverserDep = Annotated[Principal, Depends(require_permission(Permission.APPLY_REVERSE))]


@router.post(
    "/items/{item_id}/applications/{ledger_id}/reverse",
    response_model=ReverseOut,
    operation_id="reverseApplication",
)
async def reverse_application(
    item_id: int,
    ledger_id: int,
    body: ReverseIn,
    principal: ReverserDep,
    uow_factory: UowFactoryDep,
    fusion: FusionClientDep,
    runtime: RuntimeSettingsDep,
) -> ReverseOut:
    writes = await runtime.fusion_writes()
    service = ReversalService(fusion, unapply_verified=writes.unapply_verified)
    try:
        async with uow_factory() as uow:
            result = await service.reverse(
                uow,
                item_id=item_id,
                ledger_id=ledger_id,
                principal=principal,
                reason=body.reason,
                confirm_receipt_number=body.confirm_receipt_number,
            )
            await uow.commit()
    except ReversalError as exc:
        raise reversal_error_to_api(exc) from exc
    return ReverseOut(
        ledger_id=result.ledger_id,
        status="REVERSED",
        item_state=result.item_state,
        item_stage=result.item_stage,
        payment_status=result.payment_status,
    )
