"""Shared FastAPI dependency for the MCP client. Tests override it with `FakeMcpClient`."""

from typing import Annotated

from fastapi import Depends

from cashapp.api.deps import get_uow_factory
from cashapp.api.runtime_deps import RuntimeSettingsDep
from cashapp.integrations.mcp.client import McpClient
from cashapp.integrations.mcp.factory import build_mcp_client

_client: McpClient | None = None


def get_mcp_client(runtime: RuntimeSettingsDep) -> McpClient:
    """One MCP client per API process; it follows the `mcp.*` settings without a restart."""
    global _client
    if _client is None:
        _client = build_mcp_client(runtime, uow_factory=get_uow_factory())
    return _client


McpClientDep = Annotated[McpClient, Depends(get_mcp_client)]
