"""Shared FastAPI dependency for the Fusion client. Tests override it with the fake."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.deps import get_uow_factory
from cashapp.api.mcp_deps import McpClientDep
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.factory import build_fusion_client

_client: FusionClient | None = None


def get_fusion_client(runtime: RuntimeSettingsDep, mcp: McpClientDep) -> FusionClient:
    """One Fusion client per API process, built from the DB-stored settings over the shared MCP
    client."""
    global _client
    if _client is None:
        _client = build_fusion_client(runtime, uow_factory=get_uow_factory(), mcp=mcp)
    return _client


FusionClientDep = Annotated[FusionClient, Depends(get_fusion_client)]
