"""Provider of the ``LabService`` for the lab chat tools (zero-argument, built per call)."""

from typing import Any

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.deps import get_uow_factory
from cashapp.api.fusion_deps import get_fusion_client
from cashapp.api.lab_deps import get_lab_tasks
from cashapp.api.mcp_deps import get_mcp_client
from cashapp.api.runtime_deps import get_runtime_settings
from cashapp.domain.clock import SystemClock
from cashapp.services.lab.service import LabService


async def _lab_service() -> LabService:
    runtime = get_runtime_settings()
    return LabService(
        get_uow_factory(),
        await get_runtime_config(),
        get_fusion_client(runtime, get_mcp_client(runtime)),
        get_lab_tasks(),
        SystemClock(),
    )


PROVIDERS: dict[type[Any], Any] = {LabService: _lab_service}
