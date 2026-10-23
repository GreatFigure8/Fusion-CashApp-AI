"""The MCP connection's health, last call and one-click test, for the Settings and Engine boards.

Health is a live check cached in-process for 15 seconds so a page render does not call the server
every time. The test endpoint never raises for a server failure: it reports it in `error`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from cashapp.data.repositories.mcp_call_log import McpCallLogRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.principal import Principal
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.query import REST_BASE
from cashapp.integrations.mcp.client import McpClient, McpHealth
from cashapp.integrations.mcp.recorder import acting_as
from cashapp.integrations.mcp.settings import ConfigReader, load_connection

__all__ = ["McpLastCall", "McpStatus", "McpStatusService", "McpTestResult"]

_HEALTH_TTL_S = 15.0
PROBE_TOOL = "fusion_rest_get"


@dataclass(frozen=True, slots=True)
class McpLastCall:
    at: datetime
    tool: str
    rows: int | None
    duration_ms: int


@dataclass(frozen=True, slots=True)
class McpStatus:
    healthy: bool
    latency_ms: int | None
    server_url: str
    client_id: str
    source: str
    error: str | None
    last_call: McpLastCall | None


@dataclass(frozen=True, slots=True)
class McpTestResult:
    token_valid: bool
    tools_count: int
    probe_tool: str
    probe_ms: int | None
    error: str | None


class McpStatusService:
    """Build one per process: it holds the 15 second health cache."""

    def __init__(
        self,
        mcp: McpClient,
        fusion: FusionClient,
        config: ConfigReader,
        uow_factory: UowFactory,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._mcp = mcp
        self._fusion = fusion
        self._config = config
        self._uow_factory = uow_factory
        self._monotonic = monotonic
        self._cached: tuple[float, McpHealth] | None = None

    async def _health(self) -> McpHealth:
        now = self._monotonic()
        cached = self._cached
        if cached is not None and now - cached[0] < _HEALTH_TTL_S:
            return cached[1]
        health = await self._mcp.health()
        self._cached = (now, health)
        return health

    async def status(self) -> McpStatus:
        conn = await load_connection(self._config)
        health = await self._health()
        async with self._uow_factory() as uow:
            row = await uow.repo(McpCallLogRepository).latest()
        last = (
            McpLastCall(
                at=row.created_at, tool=row.tool, rows=row.row_count, duration_ms=row.duration_ms
            )
            if row is not None
            else None
        )
        return McpStatus(
            healthy=health.ok,
            latency_ms=health.latency_ms,
            server_url=conn.server_url,
            client_id=conn.client_id,
            source=conn.fusion_source,
            error=health.error,
            last_call=last,
        )

    async def test(self, principal: Principal) -> McpTestResult:
        """Token, tool listing, one REST read and the framework probe, attributed to `principal`."""
        token_valid = False
        tools_count = 0
        probe_ms: int | None = None
        error: str | None = None
        with acting_as(principal):
            try:
                conn = await load_connection(self._config)
                health = await self._mcp.health()
                token_valid = health.token_valid
                tools_count = len(health.tools)
                if not health.ok:
                    error = health.error
                else:
                    started = self._monotonic()
                    await self._mcp.call_tool(
                        PROBE_TOOL,
                        {
                            "source": conn.fusion_source,
                            "path": f"{REST_BASE}/receivablesInvoices",
                            "params": {
                                "limit": "1",
                                "fields": "TransactionNumber",
                                "onlyData": "true",
                            },
                        },
                    )
                    probe_ms = round((self._monotonic() - started) * 1000)
                    verify = getattr(self._fusion, "verify_framework", None)
                    if verify is not None:
                        await verify()
            except FusionError as exc:
                error = exc.message
            except Exception as exc:
                error = type(exc).__name__
        self._cached = None  # the next status shows what this test found
        return McpTestResult(
            token_valid=token_valid,
            tools_count=tools_count,
            probe_tool=PROBE_TOOL,
            probe_ms=probe_ms,
            error=error,
        )
