"""API contracts for the Fusion MCP connection card. Separate from the service dataclasses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from cashapp.services.mcp_status import McpLastCall, McpStatus, McpTestResult


class McpLastCallOut(BaseModel):
    at: datetime
    tool: str
    rows: int | None
    duration_ms: int

    @classmethod
    def of(cls, call: McpLastCall) -> "McpLastCallOut":
        return cls(at=call.at, tool=call.tool, rows=call.rows, duration_ms=call.duration_ms)


class McpStatusOut(BaseModel):
    healthy: bool
    latency_ms: int | None
    server_url: str
    client_id: str
    source: str
    secret_in_vault: Literal[True] = True
    error: str | None
    last_call: McpLastCallOut | None

    @classmethod
    def of(cls, status: McpStatus) -> "McpStatusOut":
        return cls(
            healthy=status.healthy,
            latency_ms=status.latency_ms,
            server_url=status.server_url,
            client_id=status.client_id,
            source=status.source,
            error=status.error,
            last_call=McpLastCallOut.of(status.last_call) if status.last_call else None,
        )


class McpTestOut(BaseModel):
    token_valid: bool
    tools_count: int
    probe_tool: Literal["fusion_rest_get"]
    probe_ms: int | None
    error: str | None

    @classmethod
    def of(cls, result: McpTestResult) -> "McpTestOut":
        return cls(
            token_valid=result.token_valid,
            tools_count=result.tools_count,
            probe_tool="fusion_rest_get",
            probe_ms=result.probe_ms,
            error=result.error,
        )
