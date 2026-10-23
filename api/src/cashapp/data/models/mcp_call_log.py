"""One row per MCP tool call: tool, source, target label and hash, rows, duration, outcome and the
acting principal. Never holds SQL text, request bodies or parameters."""

from datetime import datetime

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import UtcDateTime, identity_pk


class McpCallLog(Base):
    __tablename__ = "mcp_call_log"
    __table_args__ = (Index("IX_MCP_CALL_LOG_AT", "created_at"),)

    id: Mapped[int] = identity_pk()
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    tool: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # A REST path without its query string, or `sql:<12-char hash>`.
    target_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    target_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(10), nullable=False)  # McpCallOutcome
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    principal_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    principal_kind: Mapped[str] = mapped_column(String(10), nullable=False)  # USER or SYSTEM
