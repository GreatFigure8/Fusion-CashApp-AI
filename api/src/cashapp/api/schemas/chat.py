"""API contracts for ``POST /chat/stream``: the request body and the SSE event payloads."""

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from cashapp.services.chat.events import ChatContextRef, ChatTurnIn
from cashapp.services.chat.prompts import PromptKey
from cashapp.services.chat.service import MAX_MESSAGE_CHARS, MAX_TURNS

ITEM_ID_PATTERN = re.compile(r"^(?:WI-)?\d+$")
ACTION_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
MAX_ALLOWED_ACTIONS = 10

ActionArgs = dict[str, str | int | bool | None]


class ChatContextIn(BaseModel):
    kind: PromptKey
    id: Annotated[str | None, StringConstraints(max_length=40)] = None

    @model_validator(mode="after")
    def _item_needs_id(self) -> Self:
        if self.kind is PromptKey.ITEM and (self.id is None or not ITEM_ID_PATTERN.match(self.id)):
            raise ValueError("context.id must look like 'WI-123' or '123' for an item chat")
        return self

    def to_ref(self) -> ChatContextRef:
        if self.kind is PromptKey.ITEM and self.id is not None:
            return ChatContextRef(kind=self.kind, item_id=int(self.id.removeprefix("WI-")))
        return ChatContextRef(kind=self.kind, item_id=None)


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=MAX_MESSAGE_CHARS)]


class ChatStreamIn(BaseModel):
    context: ChatContextIn
    system_prompt_key: PromptKey
    messages: Annotated[list[ChatMessageIn], Field(min_length=1, max_length=MAX_TURNS)]
    allowed_actions: Annotated[
        list[Annotated[str, StringConstraints(pattern=ACTION_ID_PATTERN)]],
        Field(default_factory=list, max_length=MAX_ALLOWED_ACTIONS),
    ]

    @model_validator(mode="after")
    def _last_is_user(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self

    def turns(self) -> list[ChatTurnIn]:
        return [ChatTurnIn(role=m.role, content=m.content) for m in self.messages]


class TokenData(BaseModel):
    text: str


class ActionData(BaseModel):
    id: str
    label: Annotated[str, Field(max_length=80)]
    args: ActionArgs


class UsageData(BaseModel):
    model_id: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


class DoneData(BaseModel):
    usage: UsageData


class StreamErrorData(BaseModel):
    code: Literal["timeout", "llm_unavailable", "refused", "internal_error"]
    message: str


class ChatStreamEventsDoc(BaseModel):
    """Documents the SSE wire format. Each frame is exactly one of these payloads, named by its
    ``event:`` field (``token``, ``action``, ``done``, ``stream-error``) with the payload as
    ``data:``. It carries the payload models into the OpenAPI schema."""

    model_config = ConfigDict(populate_by_name=True)

    token: TokenData | None = None
    action: ActionData | None = None
    done: DoneData | None = None
    stream_error: StreamErrorData | None = Field(default=None, alias="stream-error")
