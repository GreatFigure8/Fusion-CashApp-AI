"""Assistant chat: threads, append-only messages, pending tool calls and the tool-run audit."""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import JsonDoc, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow


class ChatThread(Base):
    __tablename__ = "chat_thread"
    __table_args__ = (Index("IX_CHAT_THREAD_OWNER_UPDATED", "owner_subject", "updated_at"),)

    id: Mapped[int] = identity_pk()
    owner_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_key: Mapped[str] = mapped_column(String(20), nullable=False)
    context_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    context_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)


class ChatMessage(Base):
    """One message. ``content`` holds Anthropic content blocks verbatim (thinking included)."""

    __tablename__ = "chat_message"
    __table_args__ = (UniqueConstraint("thread_id", "seq", name="UQ_CHAT_MESSAGE_THREAD_SEQ"),)

    id: Mapped[int] = identity_pk()
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_thread.id", name="FK_CHAT_MESSAGE_THREAD"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant | tool_results
    content: Mapped[Any] = mapped_column(JsonDoc(), nullable=False)
    display_text: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)


class ChatPendingToolCall(Base):
    __tablename__ = "chat_pending_tool_call"
    __table_args__ = (
        UniqueConstraint("call_id", name="UQ_CHAT_PENDING_CALL_ID"),
        Index("IX_CHAT_PENDING_THREAD_STATUS", "thread_id", "status"),
    )

    id: Mapped[int] = identity_pk()
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("chat_thread.id", name="FK_CHAT_PENDING_THREAD"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    input: Mapped[Any] = mapped_column(JsonDoc(), nullable=False)
    principal_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    principal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    preview: Mapped[Any] = mapped_column(JsonDoc(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    # PENDING | CONFIRMED | CANCELLED | EXPIRED | FAILED | SUPERSEDED
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)


class ChatToolRun(Base):
    """The per-execution audit row. Holds ids, labels and short summaries, never full payloads."""

    __tablename__ = "chat_tool_run"
    __table_args__ = (
        Index("IX_CHAT_TOOL_RUN_AT", "at"),
        Index("IX_CHAT_TOOL_RUN_ACTOR_AT", "actor_subject", "at"),
        Index("IX_CHAT_TOOL_RUN_THREAD", "thread_id"),
    )

    id: Mapped[int] = identity_pk()
    at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    audit_label: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    input_summary: Mapped[str] = mapped_column(String(400), nullable=False)
    # OK | ERROR | FORBIDDEN | CANCELLED | EXPIRED | INVALID_INPUT | TIMEOUT
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(20), nullable=False)  # run | confirm | cancel
    summary: Mapped[str | None] = mapped_column(String(400), nullable=True)
    result_card: Mapped[Any | None] = mapped_column(JsonDoc(), nullable=True)
