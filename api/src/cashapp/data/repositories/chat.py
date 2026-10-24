"""Queries over the chat tables. Flushes, never commits."""

from sqlalchemy import func, select

from cashapp.data.models.chat import ChatMessage, ChatPendingToolCall, ChatThread, ChatToolRun
from cashapp.data.repository import BaseRepository

OPEN_STATUS = "PENDING"


class ChatThreadRepository(BaseRepository[ChatThread]):
    model = ChatThread


class ChatMessageRepository(BaseRepository[ChatMessage]):
    model = ChatMessage

    async def next_seq(self, thread_id: int) -> int:
        stmt = select(func.coalesce(func.max(ChatMessage.seq), 0)).where(
            ChatMessage.thread_id == thread_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def for_thread(self, thread_id: int) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage).where(ChatMessage.thread_id == thread_id).order_by(ChatMessage.seq)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def last_with_role(self, thread_id: int, role: str) -> ChatMessage | None:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread_id, ChatMessage.role == role)
            .order_by(ChatMessage.seq.desc())
            .limit(1)
        )
        return (await self.session.scalars(stmt)).first()


class PendingToolCallRepository(BaseRepository[ChatPendingToolCall]):
    model = ChatPendingToolCall

    async def get_for_update(self, call_id: str) -> ChatPendingToolCall | None:
        stmt = (
            select(ChatPendingToolCall)
            .where(ChatPendingToolCall.call_id == call_id)
            .with_for_update()
        )
        return (await self.session.scalars(stmt)).first()

    async def open_for_thread(self, thread_id: int) -> list[ChatPendingToolCall]:
        stmt = (
            select(ChatPendingToolCall)
            .where(
                ChatPendingToolCall.thread_id == thread_id,
                ChatPendingToolCall.status == OPEN_STATUS,
            )
            .with_for_update()
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def for_thread(self, thread_id: int) -> list[ChatPendingToolCall]:
        stmt = (
            select(ChatPendingToolCall)
            .where(ChatPendingToolCall.thread_id == thread_id)
            .order_by(ChatPendingToolCall.id)
        )
        return [*(await self.session.scalars(stmt)).all()]


class ChatToolRunRepository(BaseRepository[ChatToolRun]):
    model = ChatToolRun

    async def for_thread(self, thread_id: int) -> list[ChatToolRun]:
        stmt = (
            select(ChatToolRun).where(ChatToolRun.thread_id == thread_id).order_by(ChatToolRun.id)
        )
        return [*(await self.session.scalars(stmt)).all()]
