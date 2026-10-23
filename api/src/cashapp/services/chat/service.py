"""The chat service: validate a turn, build its context, stream Haiku's answer as events.

``prepare`` runs before the HTTP response starts (so a bad request or unknown item is a plain JSON
error); ``stream`` runs after and never raises: every failure ends the stream with a
``StreamErrorEvent``. Prompts, context and model output are never logged.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Final

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.principal import Principal
from cashapp.integrations.llm.base import (
    ChatTurn,
    LlmClient,
    LlmClients,
    LlmError,
    LlmErrorCode,
    LlmRequest,
    TextPart,
)
from cashapp.services.chat.actions import ActionBlockSplitter, parse_action_block
from cashapp.services.chat.context import ChatContextBuilder, fit_context
from cashapp.services.chat.errors import ChatInvalid, ChatNotFound
from cashapp.services.chat.events import (
    ChatContextRef,
    ChatEvent,
    ChatTurnIn,
    DoneEvent,
    StreamErrorEvent,
    TokenEvent,
)
from cashapp.services.chat.prompts import PROMPTS, PromptKey, render_system
from cashapp.services.config import RuntimeConfig

logger = logging.getLogger(__name__)

MAX_TURNS: Final = 20
MAX_MESSAGE_CHARS: Final = 4000
MAX_CONTEXT_CHARS: Final = 24000
MAX_TOKENS: Final = 2048
DEFAULT_EFFORT: Final = "low"
MAX_ALLOWED_ACTIONS: Final = 10

ERROR_MESSAGES: Final[dict[str, str]] = {
    "timeout": "The assistant didn't answer (timeout).",
    "llm_unavailable": "The assistant is unavailable right now.",
    "refused": "The assistant declined to answer.",
    "internal_error": "The assistant hit an unexpected error.",
}

__all__ = [
    "MAX_CONTEXT_CHARS",
    "MAX_MESSAGE_CHARS",
    "MAX_TOKENS",
    "MAX_TURNS",
    "ChatContextRef",
    "ChatEvent",
    "ChatInvalid",
    "ChatNotFound",
    "ChatService",
    "ChatTurnIn",
    "PreparedChat",
]


@dataclass(frozen=True, slots=True)
class PreparedChat:
    """A validated turn with its request built; holds no database session."""

    client: LlmClient
    request: LlmRequest
    allowed_actions: tuple[str, ...]
    model_id: str
    timeout_s: float


class ChatService:
    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        llm: LlmClients,
        runtime: RuntimeConfig,
        clock: Clock | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._llm = llm
        self._runtime = runtime
        self._context = ChatContextBuilder(clock)

    async def prepare(
        self,
        principal: Principal,
        ref: ChatContextRef,
        key: PromptKey,
        turns: Sequence[ChatTurnIn],
        allowed_actions: Sequence[str],
    ) -> PreparedChat:
        """Validate the turn and build the request. Raises ``ChatInvalid`` / ``ChatNotFound``."""
        # Authorization is the router's dependency; the principal is carried for audit parity.
        del principal
        self._validate(ref, key, turns, allowed_actions)
        async with self._uow_factory() as uow:
            if ref.kind is PromptKey.ITEM and ref.item_id is not None:
                doc = await self._context.item_context(uow, ref.item_id)
            else:
                doc = await self._context.flow_context(uow)
        context_json = fit_context(doc, MAX_CONTEXT_CHARS)

        role = (await self._runtime.snapshot()).models().workhorse
        client = self._llm.workhorse.with_model(role.model_id)
        *prior, last = turns
        request = LlmRequest(
            system=render_system(key, context_json, allowed_actions),
            parts=(TextPart(last.content),),
            max_tokens=MAX_TOKENS,
            timeout_s=role.timeout_s,
            purpose="chat.workhorse",
            effort=role.effort or DEFAULT_EFFORT,
            work_item_id=ref.item_id if ref.kind is PromptKey.ITEM else None,
            prompt_version=PROMPTS[key].version,
            history=tuple(ChatTurn(role=t.role, text=t.content) for t in prior),
        )
        return PreparedChat(
            client=client,
            request=request,
            allowed_actions=tuple(allowed_actions),
            model_id=client.model_id,
            timeout_s=role.timeout_s,
        )

    @staticmethod
    def _validate(
        ref: ChatContextRef,
        key: PromptKey,
        turns: Sequence[ChatTurnIn],
        allowed_actions: Sequence[str],
    ) -> None:
        if ref.kind is not key:
            raise ChatInvalid("chat_prompt_mismatch", "system_prompt_key must match context.kind")
        if ref.kind is PromptKey.ITEM and ref.item_id is None:
            raise ChatInvalid("validation_error", "context.id is required for an item chat")
        if not turns or len(turns) > MAX_TURNS:
            raise ChatInvalid("validation_error", f"messages must hold 1 to {MAX_TURNS} turns")
        if turns[-1].role != "user":
            raise ChatInvalid("validation_error", "The last message must be from the user")
        if any(not t.content or len(t.content) > MAX_MESSAGE_CHARS for t in turns):
            raise ChatInvalid(
                "validation_error", f"Each message must be 1 to {MAX_MESSAGE_CHARS} characters"
            )
        if len(allowed_actions) > MAX_ALLOWED_ACTIONS:
            raise ChatInvalid("validation_error", "Too many allowed actions")

    async def stream(self, prepared: PreparedChat) -> AsyncGenerator[ChatEvent]:
        """Token events, then the proposed actions, then ``DoneEvent``; or a ``StreamErrorEvent``.

        Never raises. Closing the consumer closes the LLM stream.
        """
        started = time.monotonic()
        deadline = started + prepared.timeout_s
        splitter = ActionBlockSplitter()
        deltas = aiter(prepared.client.stream_text(prepared.request))
        failure: StreamErrorEvent | None = None
        try:
            while True:
                try:
                    async with asyncio.timeout(max(deadline - time.monotonic(), 0.0)):
                        delta = await anext(deltas)
                except StopAsyncIteration:
                    break
                safe = splitter.feed(delta)
                if safe:
                    yield TokenEvent(safe)
        except TimeoutError:
            failure = _stream_error("timeout")
        except LlmError as exc:
            code = "refused" if exc.code is LlmErrorCode.LLM_REFUSAL else "llm_unavailable"
            logger.warning("Chat stream failed", extra={"chat_error": exc.code.value})
            failure = _stream_error(code)
        except Exception as exc:
            logger.warning("Chat stream failed", extra={"chat_error": type(exc).__name__})
            failure = _stream_error("internal_error")
        finally:
            if isinstance(deltas, AsyncGenerator):
                await deltas.aclose()
        if failure is not None:
            yield failure
            return

        rest, raw_block = splitter.finish()
        if rest:
            yield TokenEvent(rest)
        for action in parse_action_block(raw_block, prepared.allowed_actions):
            yield action
        yield DoneEvent(
            model_id=prepared.model_id, latency_ms=int((time.monotonic() - started) * 1000)
        )


def _stream_error(code: str) -> StreamErrorEvent:
    return StreamErrorEvent(code=code, message=ERROR_MESSAGES[code])
