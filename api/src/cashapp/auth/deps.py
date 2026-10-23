"""FastAPI dependencies that turn a Bearer token into a Principal and enforce permissions."""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ApiError
from cashapp.auth.tokens import TokenValidator
from cashapp.domain.principal import Permission, Principal
from cashapp.services.identity import resolve_principal
from cashapp.settings import get_settings

_bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_token_validator() -> TokenValidator:
    return TokenValidator.from_settings(get_settings().identity)


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    validator: Annotated[TokenValidator, Depends(get_token_validator)],
    uow_factory: UowFactoryDep,
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthenticated", "Sign-in required")
    claims = await validator.validate(credentials.credentials)
    async with uow_factory() as uow:
        principal = await resolve_principal(
            uow, claims, groups_claim=get_settings().identity.groups_claim
        )
    request.state.principal_subject = principal.subject
    return principal


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_permission(permission: Permission) -> Callable[..., Awaitable[Principal]]:
    """Dependency factory: 403 in the single error shape unless the caller holds `permission`."""

    async def _check(principal: PrincipalDep) -> Principal:
        if not principal.can(permission):
            raise ApiError(
                403,
                "forbidden",
                f"Missing permission {permission.value}",
                details=[{"permission": permission.value}],
            )
        return principal

    return _check
