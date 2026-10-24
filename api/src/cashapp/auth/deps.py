"""FastAPI dependencies that turn a Bearer token into a Principal and enforce permissions."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ApiError
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.auth.tokens import TokenValidator
from cashapp.auth.userinfo import UserInfoGroups
from cashapp.domain.principal import Permission, Principal
from cashapp.services.identity import resolve_principal
from cashapp.services.runtime_settings import IdentityConfig

_bearer = HTTPBearer(auto_error=False)


_validator: tuple[IdentityConfig, TokenValidator] | None = None
_userinfo = UserInfoGroups()


def get_token_validator(runtime: RuntimeSettingsDep) -> TokenValidator:
    """One validator per process (it caches the JWKS), built from the pinned identity keys."""
    global _validator
    identity = runtime.identity()
    if _validator is None or _validator[0] != identity:
        _validator = (identity, TokenValidator.from_config(identity))
    return _validator[1]


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    validator: Annotated[TokenValidator, Depends(get_token_validator)],
    uow_factory: UowFactoryDep,
    runtime: RuntimeSettingsDep,
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthenticated", "Sign-in required")
    identity = runtime.identity()
    claims = await validator.validate(credentials.credentials)
    if identity.userinfo_url and not claims.groups(identity.groups_claim):
        groups = await _userinfo.groups(
            identity.userinfo_url, credentials.credentials, identity.groups_claim
        )
        if groups:
            claims = replace(claims, raw={**claims.raw, identity.groups_claim: sorted(groups)})
    async with uow_factory() as uow:
        principal = await resolve_principal(uow, claims, groups_claim=identity.groups_claim)
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
