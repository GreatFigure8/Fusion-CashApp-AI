"""Shared FastAPI dependency for the Fusion client. Tests override it with the fake."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.deps import get_uow_factory
from cashapp.api.mcp_deps import get_mcp_client
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import build_fusion_client
from cashapp.settings import get_settings

_client: FusionClient | None = None


async def get_fusion_client() -> FusionClient:
    """One Fusion client per API process, composed over the shared MCP client."""
    global _client
    if _client is None:
        _client = build_fusion_client(
            get_settings(),
            await get_runtime_config(),
            uow_factory=get_uow_factory(),
            mcp=await get_mcp_client(),
        )
    return _client


FusionClientDep = Annotated[FusionClient, Depends(get_fusion_client)]
