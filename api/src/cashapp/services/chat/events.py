"""The chat stream's event and input shapes (plain dataclasses, no web types)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cashapp.services.chat.tools.registry import ConfirmPreview, ToolGroup

ContextKind = Literal["none", "item", "flow"]
StopReason = Literal["end_turn", "awaiting_confirmation", "tool_limit"]


@dataclass(frozen=True, slots=True)
class ChatContextRef:
    kind: ContextKind = "none"
    item_id: int | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolStarted:
    call_id: str
    tool: str
    group: ToolGroup
    summary: str
    mutating: bool


@dataclass(frozen=True, slots=True)
class ToolProgress:
    call_id: str
    done: int
    total: int


@dataclass(frozen=True, slots=True)
class ToolFinished:
    call_id: str
    tool: str
    duration_ms: int
    ok: bool
    summary: str | None = None
    result_card: dict[str, Any] | None = None  # a dumped ResultCard
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmRequired:
    call_id: str
    tool: str
    preview: ConfirmPreview
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StreamError:
    code: str
    message: str
    thread_id: int
    call_id: str | None = None
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class Done:
    thread_id: int
    message_id: int
    stop: StopReason
    model_id: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


ChatEvent = (
    TextDelta | ToolStarted | ToolProgress | ToolFinished | ConfirmRequired | StreamError | Done
)
