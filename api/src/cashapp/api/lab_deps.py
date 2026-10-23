"""FastAPI wiring for the matching lab: service, process-wide task registry, error mapping."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ApiError
from cashapp.api.fusion_deps import FusionClientDep
from cashapp.domain.clock import SystemClock
from cashapp.services.lab.errors import LabError
from cashapp.services.lab.service import LabService
from cashapp.services.lab.tasks import LabTaskRegistry


@lru_cache
def get_lab_tasks() -> LabTaskRegistry:
    """One registry per API process: replays run in the process that received the POST."""
    return LabTaskRegistry()


LabTasksDep = Annotated[LabTaskRegistry, Depends(get_lab_tasks)]


def get_lab_service(
    uow_factory: UowFactoryDep,
    config: RuntimeConfigDep,
    fusion: FusionClientDep,
    tasks: LabTasksDep,
) -> LabService:
    return LabService(uow_factory, config, fusion, tasks, SystemClock())


LabServiceDep = Annotated[LabService, Depends(get_lab_service)]


def lab_api_error(exc: LabError) -> ApiError:
    """Translate a lab service error into the API's single error shape."""
    return ApiError(exc.status, exc.code, exc.message, details=exc.details)
