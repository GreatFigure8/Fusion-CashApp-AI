"""Stored secrets: list names, set a value. Values are write-only and never returned."""

from typing import Annotated

from fastapi import APIRouter, Depends

from cashapp.api.config_deps import RuntimeConfigDep, config_api_error
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.runtime_deps import peek_runtime_settings
from cashapp.api.schemas.secrets import SecretOut, SecretUpdate
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.secrets import SecretCipher, SecretResolutionError
from cashapp.services.app_secrets import AppSecretWriter, list_secrets
from cashapp.services.config import ConfigError
from cashapp.settings import get_settings

router = APIRouter(tags=["secrets"], responses=ERROR_RESPONSES)

ReaderDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_READ))]
WriterDep = Annotated[Principal, Depends(require_permission(Permission.CONFIG_WRITE))]


def _cipher() -> SecretCipher:
    shared = peek_runtime_settings()
    settings = shared.settings if shared is not None else get_settings()
    key = settings.secrets.master_key
    if key is None:
        raise ApiError(
            503,
            "secrets_not_configured",
            "CASHAPP_SECRETS__MASTER_KEY is not set, so secrets cannot be stored",
        )
    try:
        return SecretCipher(key.get_secret_value())
    except SecretResolutionError as exc:
        raise ApiError(503, "secrets_not_configured", str(exc)) from None


@router.get("/secrets", response_model=list[SecretOut])
async def get_secrets(_: ReaderDep, uow_factory: UowFactoryDep) -> list[SecretOut]:
    async with uow_factory() as uow:
        infos = await list_secrets(uow)
    return [SecretOut.model_validate(i, from_attributes=True) for i in infos]


@router.put("/secrets/{name}", response_model=SecretOut)
async def put_secret(
    name: str,
    body: SecretUpdate,
    principal: WriterDep,
    uow_factory: UowFactoryDep,
    runtime: RuntimeConfigDep,
) -> SecretOut:
    writer = AppSecretWriter(_cipher())
    try:
        async with uow_factory() as uow:
            info = await writer.set(
                uow, name, body.value.get_secret_value(), principal, body.reason
            )
            await uow.commit()
    except ConfigError as exc:
        raise config_api_error(exc) from exc
    runtime.invalidate()
    shared = peek_runtime_settings()
    if shared is not None:
        shared.invalidate_secrets(name)
    return SecretOut.model_validate(info, from_attributes=True)
