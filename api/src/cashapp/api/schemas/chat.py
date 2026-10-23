"""API contracts for the assistant chat: the stream request, the SSE frames, confirm and threads."""

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cashapp.services.chat.events import ChatContextRef
from cashapp.services.chat.prompts import DEFAULT_PROMPT_KEY, PromptKey
from cashapp.services.chat.service import (
    MAX_MESSAGE_CHARS,
    ThreadDescription,
    ThreadMessageOut,
    ThreadToolOut,
    ToolGroupInfo,
)
from cashapp.services.chat.tools.cards import (
    CardStat,
    CardStatus,
    ExportCard,
    ReplayCard,
    ReplayCurrency,
    ResultCard,
    StateCard,
    TableCard,
    TableColumn,
)
from cashapp.services.chat.tools.registry import ConfirmPreview, ToolGroup

__all__ = [
    "CancelOut",
    "CardStat",
    "CardStatus",
    "ChatContextIn",
    "ChatStreamEventsDoc",
    "ChatStreamIn",
    "ChatThreadOut",
    "ConfirmIn",
    "ConfirmRequiredData",
    "DoneData",
    "ExportCard",
    "ReplayCard",
    "ReplayCurrency",
    "ResultCard",
    "StateCard",
    "StreamErrorData",
    "TableCard",
    "TableColumn",
    "TextDeltaData",
    "ToolFinishedData",
    "ToolGroupOut",
    "ToolProgressData",
    "ToolStartedData",
    "UsageData",
]

ITEM_ID_PATTERN = re.compile(r"^(?:WI-)?\d+$")


class ChatContextIn(BaseModel):
    kind: Literal["none", "item", "flow"] = "none"
    id: Annotated[str | None, StringConstraints(max_length=40)] = None

    @model_validator(mode="after")
    def _item_needs_id(self) -> Self:
        if self.kind == "item" and (self.id is None or not ITEM_ID_PATTERN.match(self.id)):
            raise ValueError("context.id must look like 'WI-123' or '123' for an item chat")
        return self

    def to_ref(self) -> ChatContextRef:
        if self.kind == "item" and self.id is not None:
            return ChatContextRef(kind="item", item_id=int(self.id.removeprefix("WI-")))
        return ChatContextRef(kind=self.kind, item_id=None)


class ChatStreamIn(BaseModel):
    thread_id: int | None = None
    system_prompt_key: PromptKey = DEFAULT_PROMPT_KEY
    context: ChatContextIn = Field(default_factory=ChatContextIn)
    message: Annotated[str, StringConstraints(min_length=1, max_length=MAX_MESSAGE_CHARS)]
    tool_groups: list[ToolGroup] | None = None  # only narrows the principal's tools


class ConfirmIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    expected_version: int | None = None


class CancelOut(BaseModel):
    call_id: str
    status: Literal["CANCELLED"] = "CANCELLED"


# --- SSE frame payloads ---------------------------------------------------------------------


class TextDeltaData(BaseModel):
    text: str


class ToolStartedData(BaseModel):
    call_id: str
    tool: str
    group: ToolGroup
    summary: str
    mutating: bool


class ToolProgressData(BaseModel):
    call_id: str
    done: int
    total: int


class ToolErrorData(BaseModel):
    code: str
    message: str


class ToolFinishedData(BaseModel):
    call_id: str
    tool: str
    duration_ms: int
    ok: bool
    summary: str | None = None
    result_card: ResultCard | None = None
    error: ToolErrorData | None = None


class ConfirmRequiredData(BaseModel):
    call_id: str
    tool: str
    preview: ConfirmPreview
    expires_at: datetime


class StreamErrorData(BaseModel):
    code: Literal[
        "FORBIDDEN",
        "UNKNOWN_TOOL",
        "INVALID_TOOL_INPUT",
        "TOOL_LIMIT",
        "TIMEOUT",
        "LLM_UNAVAILABLE",
        "REFUSED",
        "INTERNAL_ERROR",
    ]
    message: str
    call_id: str | None = None
    fatal: bool
    thread_id: int


class UsageData(BaseModel):
    model_id: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class DoneData(BaseModel):
    thread_id: int
    message_id: int
    stop: Literal["end_turn", "awaiting_confirmation", "tool_limit"]
    usage: UsageData


class ChatStreamEventsDoc(BaseModel):
    """Documents the SSE wire format. Each frame is exactly one of these payloads, named by its
    ``event:`` field with the payload as ``data:``. It carries the payload models into the
    OpenAPI schema."""

    model_config = ConfigDict(populate_by_name=True)

    text_delta: TextDeltaData | None = None
    tool_started: ToolStartedData | None = None
    tool_progress: ToolProgressData | None = None
    tool_finished: ToolFinishedData | None = None
    confirm_required: ConfirmRequiredData | None = None
    error: StreamErrorData | None = None
    done: DoneData | None = None


# --- tools and threads ----------------------------------------------------------------------


class ToolOut(BaseModel):
    name: str
    description: str
    mutating: bool
    allowed: bool


class ToolGroupOut(BaseModel):
    group: ToolGroup
    allowed: bool
    tools: list[ToolOut]

    @classmethod
    def from_info(cls, info: ToolGroupInfo) -> Self:
        return cls(
            group=info.group,
            allowed=info.allowed,
            tools=[
                ToolOut(
                    name=t.name,
                    description=t.description,
                    mutating=t.mutating,
                    allowed=t.allowed,
                )
                for t in info.tools
            ],
        )


class ThreadContextOut(BaseModel):
    kind: Literal["none", "item", "flow"]
    id: str | None = None


class ThreadToolRunOut(BaseModel):
    call_id: str
    tool: str
    group: ToolGroup
    summary: str
    ok: bool
    duration_ms: int
    status: Literal["done", "failed", "waiting", "cancelled", "expired"]
    result_card: ResultCard | None = None

    @classmethod
    def from_tool(cls, tool: ThreadToolOut) -> Self:
        return cls.model_validate(
            {
                "call_id": tool.call_id,
                "tool": tool.tool,
                "group": tool.group,
                "summary": tool.summary,
                "ok": tool.ok,
                "duration_ms": tool.duration_ms,
                "status": tool.status,
                "result_card": tool.result_card,
            }
        )


class ThreadMessageItemOut(BaseModel):
    id: int
    seq: int
    role: Literal["user", "assistant"]
    text: str
    tools: list[ThreadToolRunOut]
    created_at: datetime

    @classmethod
    def from_message(cls, message: ThreadMessageOut) -> Self:
        return cls(
            id=message.id,
            seq=message.seq,
            role="assistant" if message.role == "assistant" else "user",
            text=message.text,
            tools=[ThreadToolRunOut.from_tool(t) for t in message.tools],
            created_at=message.created_at,
        )


class PendingOut(BaseModel):
    call_id: str
    tool: str
    preview: ConfirmPreview
    expires_at: datetime


class ChatThreadOut(BaseModel):
    id: int
    prompt_key: PromptKey
    context: ThreadContextOut
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[ThreadMessageItemOut]
    pending: PendingOut | None = None

    @classmethod
    def from_description(cls, described: ThreadDescription) -> Self:
        thread = described.thread
        ref = thread.context
        pending = described.pending
        return cls(
            id=thread.id,
            prompt_key=PromptKey(thread.prompt_key),
            context=ThreadContextOut(
                kind=ref.kind, id=f"WI-{ref.item_id}" if ref.item_id is not None else None
            ),
            title=thread.title,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
            messages=[ThreadMessageItemOut.from_message(m) for m in described.messages],
            pending=PendingOut(
                call_id=pending.call_id,
                tool=pending.tool,
                preview=ConfirmPreview.model_validate(pending.preview),
                expires_at=pending.expires_at,
            )
            if pending is not None
            else None,
        )
