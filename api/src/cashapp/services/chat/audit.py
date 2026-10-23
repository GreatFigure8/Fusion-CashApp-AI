"""The per-execution chat tool audit: one ``CHAT_TOOL_RUN`` row for every run, confirm or cancel.

Domain audit (``CONFIG_CHANGE``, ``WORK_ITEM_HISTORY``) is written by the same services the
routers call. This row adds who asked which tool, with what outcome, and ties back to the model's
tool-use id. It never holds the payload: ``input_summary`` is a short label.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cashapp.data.models.chat import ChatToolRun
from cashapp.data.repositories.chat import ChatToolRunRepository
from cashapp.data.uow import UnitOfWork

__all__ = ["ChatToolAudit", "ToolAuditEntry"]

SUMMARY_MAX = 400


@dataclass(frozen=True, slots=True)
class ToolAuditEntry:
    at: datetime
    thread_id: int | None
    call_id: str
    tool: str
    audit_label: str
    actor_subject: str
    actor_name: str
    input_summary: str
    outcome: str  # OK | ERROR | FORBIDDEN | CANCELLED | EXPIRED | INVALID_INPUT | TIMEOUT
    error_code: str | None
    duration_ms: int
    phase: str  # run | confirm | cancel
    summary: str | None = None
    result_card: dict[str, Any] | None = None


class ChatToolAudit:
    @staticmethod
    async def record(uow: UnitOfWork, entry: ToolAuditEntry) -> ChatToolRun:
        """Add the row to the unit of work (flush, no commit)."""
        return await uow.repo(ChatToolRunRepository).add(
            ChatToolRun(
                at=entry.at,
                thread_id=entry.thread_id,
                call_id=entry.call_id,
                tool=entry.tool,
                audit_label=entry.audit_label,
                actor_subject=entry.actor_subject,
                actor_name=entry.actor_name,
                input_summary=entry.input_summary[:SUMMARY_MAX],
                outcome=entry.outcome,
                error_code=entry.error_code,
                duration_ms=entry.duration_ms,
                phase=entry.phase,
                summary=entry.summary[:SUMMARY_MAX] if entry.summary else None,
                result_card=entry.result_card,
            )
        )
