"""FastAPI wiring for runtime configuration: the shared RuntimeConfig and error translation."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.deps import get_uow_factory
from cashapp.api.errors import ApiError
from cashapp.api.schemas.config import ConfigChangeOut, ConfigChangePage
from cashapp.data.models.config import ConfigChange
from cashapp.domain.paging import Page
from cashapp.services.config import (
    ConfigConflict,
    ConfigError,
    ConfigForbidden,
    ConfigValidationError,
    RuntimeConfig,
    UnknownConfigKey,
    build_runtime_config,
)
from cashapp.services.group_roles import LastAdminMappingRemoved

_runtime: RuntimeConfig | None = None


async def get_runtime_config() -> RuntimeConfig:
    """The process-wide RuntimeConfig, built on first use. Override in tests."""
    global _runtime
    if _runtime is None:
        _runtime = build_runtime_config(get_uow_factory())
    return _runtime


RuntimeConfigDep = Annotated[RuntimeConfig, Depends(get_runtime_config)]


def config_api_error(exc: ConfigError) -> ApiError:
    """Translate a configuration service error into the API's single error shape."""
    if isinstance(exc, UnknownConfigKey):
        return ApiError(404, "config_key_not_found", f"Unknown config key {exc.key!r}")
    if isinstance(exc, ConfigConflict):
        return ApiError(
            409,
            "config_conflict",
            "The setting changed since you loaded it",
            details=[{"current_version": exc.current_version}],
        )
    if isinstance(exc, ConfigValidationError):
        return ApiError(422, "invalid_config_value", str(exc), details=exc.errors)
    if isinstance(exc, LastAdminMappingRemoved):
        return ApiError(422, "last_admin_mapping", str(exc))
    if isinstance(exc, ConfigForbidden):
        return ApiError(403, "forbidden", str(exc), details=[{"permission": "config:write"}])
    return ApiError(400, "config_error", str(exc))


def change_page(page: Page[ConfigChange]) -> ConfigChangePage:
    return ConfigChangePage(
        items=[
            ConfigChangeOut(
                id=row.id,
                key=row.key,
                old_value=row.old_value,
                new_value=row.new_value,
                changed_by=row.changed_by,
                changed_by_name=row.changed_by_name,
                changed_at=row.changed_at,
                reason=row.reason,
            )
            for row in page.items
        ],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )
