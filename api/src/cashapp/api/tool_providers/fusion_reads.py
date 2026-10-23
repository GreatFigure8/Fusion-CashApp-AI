"""Providers for the assistant's Fusion read tools (see `services/chat/tools/fusion_reads.py`)."""

from collections.abc import Awaitable, Callable

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.fusion_deps import get_fusion_client
from cashapp.api.mcp_deps import get_mcp_client
from cashapp.services.fusion_explore import FusionExploreService

Provider = Callable[[], object | Awaitable[object]]


async def _explore() -> FusionExploreService:
    return FusionExploreService(
        await get_mcp_client(), await get_fusion_client(), await get_runtime_config()
    )


PROVIDERS: dict[type, Provider] = {FusionExploreService: _explore}
