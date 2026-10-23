"""API contracts for payer aliases, and the one mapping from alias errors to the error shape."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, StringConstraints

from cashapp.api.errors import ApiError
from cashapp.data.models.aliases import PayerAlias
from cashapp.services.aliases import (
    AliasError,
    AliasForbidden,
    AliasNotFound,
    AliasValidationError,
    alias_kind,
    alias_text,
)


class AliasOut(BaseModel):
    id: int
    alias_text: str
    kind: Literal["name", "bank_account", "reference"]
    customer_number: str
    learned_from_item_id: int | None
    created_by_name: str
    created_at: datetime
    uses: int
    last_used_at: datetime | None
    retired_at: datetime | None

    @classmethod
    def from_model(cls, alias: PayerAlias) -> Self:
        return cls(
            id=alias.id,
            alias_text=alias_text(alias),
            kind=alias_kind(alias).value,
            customer_number=alias.customer_account_number,
            learned_from_item_id=alias.learned_from_item_id,
            created_by_name=alias.created_by_name,
            created_at=alias.created_at,
            uses=alias.uses,
            last_used_at=alias.last_used_at,
            retired_at=alias.retired_at,
        )


class AliasPage(BaseModel):
    items: list[AliasOut]
    total: int
    offset: int
    limit: int


class RetireAliasIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def alias_error_to_api(exc: AliasError) -> ApiError:
    if isinstance(exc, AliasNotFound):
        return ApiError(404, "alias_not_found", f"Alias {exc.alias_id} not found")
    if isinstance(exc, AliasForbidden):
        details = [{"permission": exc.permission.value}] if exc.permission is not None else []
        return ApiError(403, "forbidden", str(exc), details=details)
    if isinstance(exc, AliasValidationError):
        return ApiError(422, "invalid_alias", exc.message, details=[{"msg": exc.message}])
    return ApiError(400, "alias_error", str(exc))
