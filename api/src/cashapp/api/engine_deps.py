"""FastAPI wiring for engine control: the one EngineService per process and error translation."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.bus_deps import get_bus_health, get_event_bus
from cashapp.api.config_deps import config_api_error, get_runtime_config
from cashapp.api.deps import get_uow_factory
from cashapp.api.errors import ApiError
from cashapp.domain.clock import SystemClock
from cashapp.services.autofix.requeue import RequeueService
from cashapp.services.config import ConfigConflict, ConfigError
from cashapp.services.engine.service import (
    EngineConflict,
    EngineError,
    EngineForbidden,
    EngineReasonRequired,
    EngineService,
    ThrottleOutOfBounds,
    UnknownStation,
)
from cashapp.services.locking import LockService
from cashapp.settings import get_settings

_service: EngineService | None = None


async def get_engine_service() -> EngineService:
    """The process-wide EngineService (its status cache is shared by every caller).

    Tests override this dependency.
    """
    global _service
    if _service is None:
        clock = SystemClock()
        config = await get_runtime_config()
        locks = LockService(config, clock)
        _service = EngineService(
            uow_factory=get_uow_factory(),
            config=config,
            bus_health=get_bus_health(),
            settings=get_settings(),
            clock=clock,
            lock_service=locks,
            requeue=RequeueService(lock_service=locks, clock=clock),
            bus=get_event_bus(),
        )
    return _service


EngineServiceDep = Annotated[EngineService, Depends(get_engine_service)]


def engine_api_error(exc: EngineError | ConfigError) -> ApiError:
    """Translate an engine service error into the API's single error shape."""
    if isinstance(exc, EngineConflict):
        return ApiError(
            409,
            "conflict",
            "The engine settings changed since you loaded them",
            details=[
                {
                    "expected_version": exc.expected_version,
                    "current_version": exc.current_version,
                }
            ],
        )
    if isinstance(exc, ConfigConflict):
        return ApiError(
            409,
            "conflict",
            "The engine settings changed since you loaded them",
            details=[
                {
                    "expected_version": exc.expected_version,
                    "current_version": exc.current_version,
                }
            ],
        )
    if isinstance(exc, EngineReasonRequired):
        return ApiError(422, "validation_error", str(exc), details=[{"loc": ["body", "reason"]}])
    if isinstance(exc, ThrottleOutOfBounds):
        return ApiError(422, "validation_error", str(exc))
    if isinstance(exc, EngineForbidden):
        return ApiError(403, "forbidden", str(exc), details=[{"permission": "engine:control"}])
    if isinstance(exc, UnknownStation):
        return ApiError(404, "not_found", str(exc))
    if isinstance(exc, ConfigError):
        return config_api_error(exc)
    return ApiError(400, "engine_error", str(exc))
