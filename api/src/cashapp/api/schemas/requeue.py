"""API contract for human requeue, and the mapping from requeue errors to the error shape."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from cashapp.api.errors import ApiError
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.stages import ItemState, Stage
from cashapp.services.autofix.requeue import (
    InvalidTargetStage,
    ItemNotRequeueable,
    RequeueError,
    RequeueResult,
)


class RequeueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_stage: Stage | None = None
    corrected_extraction: RemittanceExtraction | None = None
    customer_number: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
        | None
    ) = None
    receipt_id: Annotated[int, Field(gt=0)] | None = None
    learn_alias: bool = True
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class FieldChangeOut(BaseModel):
    path: str
    before: Any = None
    after: Any = None


class RequeueOut(BaseModel):
    item_id: int
    stage: Stage
    state: ItemState
    changes: list[FieldChangeOut]
    alias_learned: bool

    @classmethod
    def from_result(cls, result: RequeueResult) -> "RequeueOut":
        return cls(
            item_id=result.item_id,
            stage=result.stage,
            state=result.state,
            changes=[
                FieldChangeOut(path=change.path, before=change.before, after=change.after)
                for change in result.changes
            ],
            alias_learned=result.alias_id is not None,
        )


def requeue_error_to_api(exc: RequeueError) -> ApiError:
    if isinstance(exc, ItemNotRequeueable):
        return ApiError(
            409,
            "item_not_requeueable",
            f"The item is {exc.state.value} and cannot be requeued",
            details=[{"state": exc.state.value}],
        )
    if isinstance(exc, InvalidTargetStage):
        return ApiError(
            422,
            "invalid_target_stage",
            exc.reason,
            details=[{"target_stage": exc.target_stage, "reason": exc.reason}],
        )
    return ApiError(400, "requeue_error", str(exc))
