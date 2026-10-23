"""The fusion-sql-mcp (Greenlight) client: transport, token, call recording and errors."""

from cashapp.integrations.mcp.client import (
    REQUIRED_TOOLS,
    McpClient,
    McpClientOptions,
    McpHealth,
    StreamableHttpMcpClient,
)
from cashapp.integrations.mcp.errors import McpError, error_from_tool_text
from cashapp.integrations.mcp.factory import build_mcp_client
from cashapp.integrations.mcp.fake import FakeMcpClient
from cashapp.integrations.mcp.recorder import (
    DbMcpCallRecorder,
    InMemoryMcpCallRecorder,
    McpCallEntry,
    McpCallRecorder,
    acting_as,
)
from cashapp.integrations.mcp.settings import ConfigReader, McpConnection, load_connection

__all__ = [
    "REQUIRED_TOOLS",
    "ConfigReader",
    "DbMcpCallRecorder",
    "FakeMcpClient",
    "InMemoryMcpCallRecorder",
    "McpCallEntry",
    "McpCallRecorder",
    "McpClient",
    "McpClientOptions",
    "McpConnection",
    "McpError",
    "McpHealth",
    "StreamableHttpMcpClient",
    "acting_as",
    "build_mcp_client",
    "error_from_tool_text",
    "load_connection",
]
