"""The LLM interface every station consumes, and the request/result shapes around it.

Exactly two real implementations sit behind ``LlmClient`` (Anthropic and OCI Cohere) plus one
replay fake. Stations never know which one they hold. Nothing here carries prompt or artifact
text into an error message: ``LlmError.detail`` is for ids, codes and counts only.
"""

import hashlib
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel

from cashapp.domain.error_codes import ErrorCode

if TYPE_CHECKING:
    from cashapp.services.config_groups import ModelsConfig

__all__ = [
    "ChatTurn",
    "ContentPart",
    "ImagePart",
    "LlmClient",
    "LlmClients",
    "LlmError",
    "LlmErrorCode",
    "LlmRequest",
    "LlmResult",
    "LlmUsage",
    "PdfPart",
    "TextPart",
    "ToolCallingLlm",
    "ToolTurnComplete",
    "ToolTurnDelta",
    "ToolTurnEvent",
    "ToolTurnRequest",
    "parts_digest",
]


@dataclass(frozen=True, slots=True)
class TextPart:
    text: str
    kind: Literal["text"] = "text"


@dataclass(frozen=True, slots=True)
class ImagePart:
    data: bytes
    media_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
    kind: Literal["image"] = "image"


@dataclass(frozen=True, slots=True)
class PdfPart:
    data: bytes
    kind: Literal["pdf"] = "pdf"


ContentPart = TextPart | ImagePart | PdfPart


def parts_digest(parts: Sequence[ContentPart]) -> str:
    """SHA-256 hex over each part's kind, media type, length and bytes, in order (replay key)."""
    digest = hashlib.sha256()
    for part in parts:
        data = part.text.encode("utf-8") if isinstance(part, TextPart) else part.data
        media_type = part.media_type if isinstance(part, ImagePart) else ""
        digest.update(f"{part.kind}\x00{media_type}\x00{len(data)}\x00".encode())
        digest.update(data)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    system: str
    parts: tuple[ContentPart, ...]
    max_tokens: int
    timeout_s: float
    purpose: str  # "<station>.<role>", e.g. "extract.reader_a", "classify.workhorse"
    effort: str | None = None  # low | medium | high | xhigh | max; ignored by Cohere
    work_item_id: int | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    history: tuple[ChatTurn, ...] = ()  # prior turns for stream_text; empty for parse


@dataclass(frozen=True, slots=True)
class LlmUsage:
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class LlmResult[T: BaseModel]:
    output: T | None  # None if and only if the model refused
    refused: bool
    stop_reason: str  # the provider's stop or finish reason, verbatim
    usage: LlmUsage
    response_id: str | None = None


class LlmErrorCode(StrEnum):
    """Values are ``ErrorCode`` member values, so the auto-fix engine needs no translation."""

    LLM_TRANSIENT = "LLM_TRANSIENT"
    LLM_REFUSAL = "LLM_REFUSAL"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class LlmError(Exception):
    """A failed model call. ``detail`` never contains prompt, artifact or output text."""

    def __init__(
        self,
        code: LlmErrorCode,
        detail: str,
        *,
        provider: str,
        model_id: str,
        usage: LlmUsage | None = None,
    ) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail
        self.provider = provider
        self.model_id = model_id
        self.usage = usage

    @property
    def error_code(self) -> ErrorCode:
        return ErrorCode(self.code.value)


class LlmClient(Protocol):
    @property
    def provider(self) -> str:
        """``anthropic``, ``oci-cohere`` or ``replay``."""
        ...

    @property
    def model_id(self) -> str: ...

    def with_model(self, model_id: str) -> Self:
        """A client for another model on the same transport (cheap; no new connection)."""
        ...

    async def parse[T: BaseModel](self, request: LlmRequest, schema: type[T]) -> LlmResult[T]:
        """Structured output validated against ``schema``. A refusal is a result, not an error."""
        ...

    def stream_text(self, request: LlmRequest) -> AsyncIterator[str]:
        """Text deltas of a plain-text reply. Raises ``LlmError``."""
        ...


@dataclass(frozen=True, slots=True)
class ToolTurnRequest:
    """One model turn of the tool-using chat: whole history, offered tools, no sampling knobs."""

    system: str
    messages: tuple[dict[str, Any], ...]  # Anthropic message dicts, thinking blocks verbatim
    tools: tuple[dict[str, Any], ...]
    max_tokens: int
    timeout_s: float
    purpose: str
    effort: str | None = None
    work_item_id: int | None = None
    prompt_version: str | None = None


@dataclass(frozen=True, slots=True)
class ToolTurnDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolTurnComplete:
    content: tuple[dict[str, Any], ...]  # the final content blocks, verbatim
    stop_reason: str
    usage: LlmUsage


type ToolTurnEvent = ToolTurnDelta | ToolTurnComplete


@runtime_checkable
class ToolCallingLlm(Protocol):
    """A client that can run a tool-using turn. Separate from ``LlmClient``: Cohere lacks it."""

    def stream_tool_turn(self, request: ToolTurnRequest) -> AsyncIterator[ToolTurnEvent]:
        """Text deltas, then one ``ToolTurnComplete``. Raises ``LlmError`` (a refusal included)."""
        ...


@dataclass(frozen=True, slots=True)
class LlmClients:
    reader_a: LlmClient
    reader_b: LlmClient
    adjudicator: LlmClient
    workhorse: LlmClient

    def with_models(self, models: "ModelsConfig") -> "LlmClients":
        """Rebind each role to the model id in ``models``; stations call this once per event."""
        return LlmClients(
            reader_a=self.reader_a.with_model(models.reader_a.model_id),
            reader_b=self.reader_b.with_model(models.reader_b.model_id),
            adjudicator=self.adjudicator.with_model(models.adjudicator.model_id),
            workhorse=self.workhorse.with_model(models.workhorse.model_id),
        )
