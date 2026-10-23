"""The chat stream's event and input shapes (plain dataclasses, no web types)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from cashapp.services.chat.prompts import PromptKey

ActionArgValue = str | int | bool | None


@dataclass(frozen=True, slots=True)
class ChatContextRef:
    kind: PromptKey
    item_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChatTurnIn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class TokenEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ActionEvent:
    id: str
    label: str
    args: Mapping[str, ActionArgValue]


@dataclass(frozen=True, slots=True)
class DoneEvent:
    model_id: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class StreamErrorEvent:
    code: str
    message: str


ChatEvent = TokenEvent | ActionEvent | DoneEvent | StreamErrorEvent
