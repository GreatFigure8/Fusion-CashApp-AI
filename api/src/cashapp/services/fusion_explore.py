"""Read-only exploration of Fusion through the MCP server: SQL, REST and the source list.

Used by the assistant's Fusion tools. Everything here reads. The SQL guard runs before any
server call, and the row cap comes from `mcp.max_rows`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.query import REST_BASE
from cashapp.integrations.mcp.client import McpClient
from cashapp.integrations.mcp.settings import ConfigReader, McpConnection, load_connection
from cashapp.integrations.mcp.sql import assert_single_select

__all__ = ["ExploreRows", "ExploreSource", "FusionExploreService"]


@dataclass(frozen=True, slots=True)
class ExploreRows:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    total_rows: int | None


@dataclass(frozen=True, slots=True)
class ExploreSource:
    name: str
    kind: str
    environment: str | None


@dataclass(frozen=True, slots=True)
class ExploreRest:
    status: int
    body: dict[str, Any]
    has_more: bool | None


class FusionExploreService:
    def __init__(self, mcp: McpClient, fusion: FusionClient, config: ConfigReader) -> None:
        self._mcp = mcp
        self._fusion = fusion
        self._config = config

    async def _connection(self) -> McpConnection:
        conn = await load_connection(self._config)
        if not conn.fusion_source:
            raise FusionError(
                ErrorCode.FUSION_FAULT,
                "no Fusion source is configured (set mcp.fusion_source)",
                retryable=False,
            )
        return conn

    async def query(self, sql: str, max_rows: int | None = None) -> ExploreRows:
        """Run one SELECT/WITH. Anything else is refused before the server is called."""
        statement = assert_single_select(sql)
        conn = await self._connection()
        cap = conn.max_rows if max_rows is None else max(1, min(max_rows, conn.max_rows))
        out = await self._mcp.call_tool(
            "run_query", {"source": conn.fusion_source, "sql": statement, "max_rows": cap}
        )
        total = out.get("total_rows")
        return ExploreRows(
            columns=[str(c) for c in cast("list[Any]", out.get("columns", []))],
            rows=[list(r) for r in cast("list[Any]", out.get("rows", []))],
            truncated=out.get("truncated") is True,
            total_rows=total if isinstance(total, int) else None,
        )

    async def rest_get(self, path: str, params: dict[str, str] | None = None) -> ExploreRest:
        """One page of a REST resource, through the same read path every station uses."""
        body = await self._fusion.rest_get(path, params)
        has_more = body.get("hasMore")
        return ExploreRest(
            status=200, body=body, has_more=has_more if isinstance(has_more, bool) else None
        )

    async def rest_describe(self, path: str) -> ExploreRest:
        conn = await self._connection()
        full = path if path.startswith("/") else f"{REST_BASE}/{path}"
        out = await self._mcp.call_tool(
            "fusion_rest_describe", {"source": conn.fusion_source, "path": full}
        )
        body = out.get("body")
        status = out.get("status")
        return ExploreRest(
            status=status if isinstance(status, int) else 200,
            body=cast("dict[str, Any]", body) if isinstance(body, dict) else {},
            has_more=None,
        )

    async def list_sources(self) -> list[ExploreSource]:
        out = await self._mcp.call_tool("list_sources", {})
        sources: list[ExploreSource] = []
        for entry in cast("list[Any]", out.get("result", [])):
            if not isinstance(entry, dict):
                continue
            row = cast("dict[str, Any]", entry)
            environment = row.get("environment")
            sources.append(
                ExploreSource(
                    name=str(row.get("name", "")),
                    kind=str(row.get("kind", "")),
                    environment=environment if isinstance(environment, str) else None,
                )
            )
        return sources
