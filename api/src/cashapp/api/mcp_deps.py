"""Shared FastAPI dependency for the MCP client. Tests override it with `FakeMcpClient`."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.config_deps import get_runtime_config
from cashapp.api.deps import get_uow_factory
from cashapp.integrations.mcp.client import McpClient
from cashapp.integrations.mcp.factory import build_mcp_client
from cashapp.settings import get_settings

_client: McpClient | None = None


async def get_mcp_client() -> McpClient:
    """One MCP client per API process; it follows the `mcp.*` settings without a restart."""
    global _client
    if _client is None:
        _client = build_mcp_client(
            get_settings(), await get_runtime_config(), uow_factory=get_uow_factory()
        )
    return _client


McpClientDep = Annotated[McpClient, Depends(get_mcp_client)]
