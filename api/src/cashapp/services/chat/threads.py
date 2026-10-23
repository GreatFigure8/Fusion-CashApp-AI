"""Threads, append-only messages and pending tool calls.

Messages hold the Anthropic content blocks verbatim (thinking blocks included) and are never
rewritten once the model has seen them. The one exception is a staged ``tool_results`` message:
while a changing tool waits for the person, its block is a placeholder, completed in place at
confirm, cancel, expiry or supersede, before any model call reads it. Message text is customer
data: nothing here logs it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

from cashapp.data.models.chat import ChatMessage, ChatPendingToolCall, ChatThread, ChatToolRun
from cashapp.data.repositories.chat import (
    ChatMessageRepository,
    ChatThreadRepository,
    ChatToolRunRepository,
    PendingToolCallRepository,
)
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.principal import Principal
from cashapp.services.chat.errors import ThreadNotFound, ToolCallConflict, ToolCallNotFound
from cashapp.services.chat.events import ChatContextRef, ContextKind

TITLE_MAX: Final = 80
AWAITING_TEXT: Final = "Waiting for the person to confirm."

PENDING: Final = "PENDING"
CONFIRMED: Final = "CONFIRMED"
CANCELLED: Final = "CANCELLED"
EXPIRED: Final = "EXPIRED"
FAILED: Final = "FAILED"
SUPERSEDED: Final = "SUPERSEDED"

__all__ = ["PendingInfo", "ThreadInfo", "ThreadService", "ThreadView", "tool_result_block"]


@dataclass(frozen=True, slots=True)
class ThreadInfo:
    id: int
    owner_subject: str
    prompt_key: str
    context: ChatContextRef
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PendingInfo:
    call_id: str
    thread_id: int
    tool: str
    input: dict[str, Any]
    principal_subject: str
    principal_name: str
    preview: dict[str, Any]
    expires_at: datetime
    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class MessageRow:
    id: int
    seq: int
    role: str
    content: Any
    display_text: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ToolRunRow:
    call_id: str
    outcome: str
    phase: str
    duration_ms: int
    summary: str | None
    result_card: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ThreadView:
    thread: ThreadInfo
    messages: list[MessageRow]
    runs: list[ToolRunRow]
    pending: list[PendingInfo]


def tool_result_block(call_id: str, content: str, *, is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if is_error:
        block["is_error"] = True
    return block


def _info(row: ChatThread) -> ThreadInfo:
    kind: ContextKind = (
        "item" if row.context_kind == "item" else ("flow" if row.context_kind == "flow" else "none")
    )
    return ThreadInfo(
        id=row.id,
        owner_subject=row.owner_subject,
        prompt_key=row.prompt_key,
        context=ChatContextRef(kind=kind, item_id=row.context_id),
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _pending_info(row: ChatPendingToolCall) -> PendingInfo:
    return PendingInfo(
        call_id=row.call_id,
        thread_id=row.thread_id,
        tool=row.tool,
        input=dict(row.input),
        principal_subject=row.principal_subject,
        principal_name=row.principal_name,
        preview=dict(row.preview),
        expires_at=row.expires_at,
        status=row.status,
        reason=row.reason,
    )


class ThreadService:
    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    # --- threads --------------------------------------------------------------------------

    async def create(
        self, principal: Principal, prompt_key: str, ref: ChatContextRef, first_message: str
    ) -> ThreadInfo:
        now = self._clock.now()
        title = " ".join(first_message.split())[:TITLE_MAX] or "Conversation"
        async with self._uow_factory() as uow:
            row = await uow.repo(ChatThreadRepository).add(
                ChatThread(
                    owner_subject=principal.subject,
                    owner_name=principal.display_name,
                    prompt_key=prompt_key,
                    context_kind=ref.kind,
                    context_id=ref.item_id,
                    title=title,
                    created_at=now,
                    updated_at=now,
                )
            )
            await uow.commit()
            return _info(row)

    async def get_owned(self, principal: Principal, thread_id: int) -> ThreadInfo:
        async with self._uow_factory() as uow:
            return _info(await self._owned(uow, principal, thread_id))

    @staticmethod
    async def _owned(uow: UnitOfWork, principal: Principal, thread_id: int) -> ChatThread:
        row = await uow.repo(ChatThreadRepository).get(thread_id)
        if row is None or row.owner_subject != principal.subject:
            raise ThreadNotFound(thread_id)
        return row

    # --- messages -------------------------------------------------------------------------

    async def append(
        self, thread_id: int, role: str, content: Any, display_text: str | None = None
    ) -> int:
        """Append a message (never edits an earlier one); returns its id."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            repo = uow.repo(ChatMessageRepository)
            row = await repo.add(
                ChatMessage(
                    thread_id=thread_id,
                    seq=await repo.next_seq(thread_id),
                    role=role,
                    content=content,
                    display_text=display_text[:4000] if display_text else None,
                    created_at=now,
                )
            )
            thread = await uow.repo(ChatThreadRepository).get(thread_id)
            if thread is not None:
                thread.updated_at = now
            await uow.commit()
            return row.id

    async def messages_for_model(self, thread_id: int) -> list[dict[str, Any]]:
        """The history as Anthropic messages. Consecutive user-side messages are merged.

        A ``tool_results`` message and the next person message both go in the user role; the API
        wants them in one turn, tool results first.
        """
        async with self._uow_factory() as uow:
            rows = await uow.repo(ChatMessageRepository).for_thread(thread_id)
        messages: list[dict[str, Any]] = []
        for row in rows:
            role = "assistant" if row.role == "assistant" else "user"
            blocks = _as_blocks(row.content)
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"] = [*messages[-1]["content"], *blocks]
            else:
                messages.append({"role": role, "content": blocks})
        return messages

    async def complete_tool_result(
        self, thread_id: int, call_id: str, content: str, *, is_error: bool
    ) -> None:
        """Replace the placeholder for ``call_id`` in the staged tool-results message."""
        async with self._uow_factory() as uow:
            await self._complete(uow, thread_id, call_id, content, is_error=is_error)
            await uow.commit()

    @staticmethod
    async def _complete(
        uow: UnitOfWork, thread_id: int, call_id: str, content: str, *, is_error: bool
    ) -> None:
        row = await uow.repo(ChatMessageRepository).last_with_role(thread_id, "tool_results")
        if row is None:
            return
        blocks: list[Any] = [
            tool_result_block(call_id, content, is_error=is_error)
            if isinstance(block, dict)
            and cast("dict[str, Any]", block).get("tool_use_id") == call_id
            else block
            for block in _as_blocks(row.content)
        ]
        row.content = blocks  # a new list, so the change is seen

    # --- pending calls --------------------------------------------------------------------

    async def create_pending(
        self,
        thread_id: int,
        principal: Principal,
        call_id: str,
        tool: str,
        tool_input: dict[str, Any],
        preview: dict[str, Any],
        expires_at: datetime,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.repo(PendingToolCallRepository).add(
                ChatPendingToolCall(
                    call_id=call_id,
                    thread_id=thread_id,
                    tool=tool,
                    input=tool_input,
                    principal_subject=principal.subject,
                    principal_name=principal.display_name,
                    preview=preview,
                    expires_at=expires_at,
                    status=PENDING,
                    created_at=self._clock.now(),
                )
            )
            await uow.commit()

    async def supersede_open(self, thread_id: int) -> list[str]:
        """Mark every open call of the thread SUPERSEDED and complete its placeholder."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            open_calls = await uow.repo(PendingToolCallRepository).open_for_thread(thread_id)
            for call in open_calls:
                call.status = SUPERSEDED
                call.decided_at = now
                await self._complete(
                    uow,
                    thread_id,
                    call.call_id,
                    "superseded: the person sent a new message instead of confirming.",
                    is_error=True,
                )
            await uow.commit()
            return [call.call_id for call in open_calls]

    async def claim_pending(self, principal: Principal, call_id: str, reason: str) -> PendingInfo:
        """Atomically move a call from PENDING to CONFIRMED for its owner, or raise.

        Raises ``ToolCallNotFound`` (404) or ``ToolCallConflict`` (``tool_call_not_yours``,
        ``tool_call_decided``, ``tool_call_expired``). The caller checks the tool permission
        between ownership and the status checks via ``peek_pending``.
        """
        now = self._clock.now()
        async with self._uow_factory() as uow:
            row = await uow.repo(PendingToolCallRepository).get_for_update(call_id)
            if row is None:
                raise ToolCallNotFound(call_id)
            if row.principal_subject != principal.subject:
                raise ToolCallConflict("tool_call_not_yours")
            if row.status != PENDING:
                raise ToolCallConflict("tool_call_decided")
            if row.expires_at <= now:
                row.status = EXPIRED
                row.decided_at = now
                await self._complete(
                    uow, row.thread_id, call_id, "expired before it was confirmed.", is_error=True
                )
                await uow.commit()
                raise ToolCallConflict("tool_call_expired")
            row.status = CONFIRMED
            row.decided_at = now
            row.decided_by = principal.subject
            row.reason = reason
            info = _pending_info(row)
            await uow.commit()
            return info

    async def peek_pending(self, principal: Principal, call_id: str) -> PendingInfo:
        """The call for its owner without deciding it (404 unknown, 409 not yours)."""
        async with self._uow_factory() as uow:
            row = await uow.repo(PendingToolCallRepository).get_for_update(call_id)
            if row is None:
                raise ToolCallNotFound(call_id)
            if row.principal_subject != principal.subject:
                raise ToolCallConflict("tool_call_not_yours")
            return _pending_info(row)

    async def cancel_pending(self, principal: Principal, call_id: str) -> PendingInfo:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            row = await uow.repo(PendingToolCallRepository).get_for_update(call_id)
            if row is None:
                raise ToolCallNotFound(call_id)
            if row.principal_subject != principal.subject:
                raise ToolCallConflict("tool_call_not_yours")
            if row.status != PENDING:
                raise ToolCallConflict("tool_call_decided")
            row.status = CANCELLED
            row.decided_at = now
            row.decided_by = principal.subject
            await self._complete(
                uow, row.thread_id, call_id, "cancelled: the person declined it.", is_error=True
            )
            info = _pending_info(row)
            await uow.commit()
            return info

    async def mark_failed(self, call_id: str) -> None:
        async with self._uow_factory() as uow:
            row = await uow.repo(PendingToolCallRepository).get_for_update(call_id)
            if row is not None:
                row.status = FAILED
            await uow.commit()

    # --- views ----------------------------------------------------------------------------

    async def view(self, principal: Principal, thread_id: int) -> ThreadView:
        async with self._uow_factory() as uow:
            thread = _info(await self._owned(uow, principal, thread_id))
            messages = await uow.repo(ChatMessageRepository).for_thread(thread_id)
            runs = await uow.repo(ChatToolRunRepository).for_thread(thread_id)
            pending = await uow.repo(PendingToolCallRepository).for_thread(thread_id)
        return ThreadView(
            thread=thread,
            messages=[
                MessageRow(m.id, m.seq, m.role, m.content, m.display_text, m.created_at)
                for m in messages
            ],
            runs=[_run_row(r) for r in runs],
            pending=[_pending_info(p) for p in pending],
        )


def _run_row(row: ChatToolRun) -> ToolRunRow:
    stored: Any = row.result_card
    card = cast("dict[str, Any]", stored) if isinstance(stored, dict) else None
    return ToolRunRow(
        call_id=row.call_id,
        outcome=row.outcome,
        phase=row.phase,
        duration_ms=row.duration_ms,
        summary=row.summary,
        result_card=card,
    )


def _as_blocks(content: Any) -> list[Any]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, Sequence):
        return list(content)  # pyright: ignore[reportUnknownArgumentType]
    return []
