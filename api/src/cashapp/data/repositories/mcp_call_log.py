"""Queries over MCP_CALL_LOG. Flushes, never commits."""

from datetime import datetime
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from cashapp.data.models.mcp_call_log import McpCallLog
from cashapp.data.repository import BaseRepository


class McpCallLogRepository(BaseRepository[McpCallLog]):
    model = McpCallLog

    async def latest(self) -> McpCallLog | None:
        """The most recent call of any tool, or None when nothing has been recorded."""
        stmt = select(McpCallLog).order_by(McpCallLog.created_at.desc(), McpCallLog.id.desc())
        return (await self.session.scalars(stmt.limit(1))).first()

    async def purge_before(self, cutoff: datetime) -> int:
        """Delete rows older than `cutoff`; returns how many went."""
        result = cast(
            "CursorResult[tuple[()]]",
            await self.session.execute(delete(McpCallLog).where(McpCallLog.created_at < cutoff)),
        )
        await self.session.flush()
        return int(result.rowcount or 0)
