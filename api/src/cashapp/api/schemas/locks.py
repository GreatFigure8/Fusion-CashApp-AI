"""API contracts for item locks, and the one mapping from lock errors to the error shape."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, StringConstraints

from cashapp.api.errors import ApiError
from cashapp.services.locking import (
    ItemBusy,
    ItemNotFound,
    LockConflict,
    LockError,
    LockForbidden,
    LockInfo,
    LockNotHeld,
    LockReasonRequired,
)


class LockInfoOut(BaseModel):
    item_id: int
    owner: str
    owner_name: str
    acquired_at: datetime
    expires_at: datetime

    @classmethod
    def from_info(cls, info: LockInfo | None) -> Self | None:
        if info is None:
            return None
        return cls(
            item_id=info.item_id,
            owner=info.owner,
            owner_name=info.owner_name,
            acquired_at=info.acquired_at,
            expires_at=info.expires_at,
        )


class ForceTakeIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def lock_error_to_api(exc: LockError) -> ApiError:
    if isinstance(exc, ItemNotFound):
        return ApiError(404, "item_not_found", f"Item {exc.item_id} not found")
    if isinstance(exc, LockConflict):
        return ApiError(
            409,
            "lock_conflict",
            f"Locked by {exc.owner_name}",
            details=[{"owner_name": exc.owner_name, "acquired_at": exc.acquired_at.isoformat()}],
        )
    if isinstance(exc, ItemBusy):
        return ApiError(409, "item_busy", "The pipeline is processing this item right now")
    if isinstance(exc, LockNotHeld):
        return ApiError(409, "lock_not_held", "You do not hold the lock on this item")
    if isinstance(exc, LockForbidden):
        return ApiError(403, "forbidden", str(exc), details=[{"permission": "items:work"}])
    if isinstance(exc, LockReasonRequired):
        return ApiError(422, "lock_reason_required", "A reason is required to take a lock")
    return ApiError(400, "lock_error", str(exc))
