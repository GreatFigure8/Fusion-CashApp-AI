"""API contracts for classification, and the mapping from its errors to the error shape."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, StringConstraints

from cashapp.api.errors import ApiError
from cashapp.data.models.classification import Classification
from cashapp.domain.classification import ClassificationOrigin
from cashapp.domain.principal import Permission
from cashapp.domain.stages import ItemState, Stage
from cashapp.services.classification import ClassificationForbidden, InvalidClassificationState


class ClassificationOverrideIn(BaseModel):
    is_remittance: bool
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ClassificationOut(BaseModel):
    id: int
    work_item_id: int
    is_remittance: bool
    reason: str
    confidence: float | None
    model_id: str | None
    prompt_version: str | None
    origin: ClassificationOrigin
    decided_by: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: Classification) -> Self:
        return cls(
            id=row.id,
            work_item_id=row.work_item_id,
            is_remittance=row.is_remittance,
            reason=row.reason,
            confidence=row.confidence,
            model_id=row.model_id,
            prompt_version=row.prompt_version,
            origin=row.origin,
            decided_by=row.decided_by,
            created_at=row.created_at,
        )


class ClassificationOverrideOut(BaseModel):
    classification: ClassificationOut
    stage: Stage
    state: ItemState


def classification_error_to_api(
    exc: InvalidClassificationState | ClassificationForbidden,
) -> ApiError:
    if isinstance(exc, InvalidClassificationState):
        return ApiError(
            409,
            "invalid_state",
            "The item is past classification",
            details=[{"stage": exc.stage.value, "state": exc.state.value}],
        )
    return ApiError(
        403,
        "forbidden",
        "You may not override classifications",
        details=[{"permission": Permission.CLASSIFICATION_OVERRIDE.value}],
    )
