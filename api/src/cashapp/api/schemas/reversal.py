"""API contracts for reversing an automated application, and the one error mapping."""

from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from cashapp.api.errors import ApiError
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.services.reversal import ReversalError


class ReverseIn(BaseModel):
    # A blank reason reaches the service, which answers 422 reason_required.
    reason: Annotated[str, StringConstraints(max_length=1000)]
    confirm_receipt_number: Annotated[str, StringConstraints(max_length=100)]


class ReverseOut(BaseModel):
    ledger_id: int
    status: Literal["REVERSED"]
    item_state: ItemState
    item_stage: Stage
    payment_status: PaymentStatus | None


def reversal_error_to_api(exc: ReversalError) -> ApiError:
    return ApiError(exc.status_code, exc.code, exc.message, details=exc.details)
