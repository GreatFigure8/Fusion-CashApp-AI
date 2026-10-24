"""The chat agent: Haiku with tools, one streamed turn at a time, mutations only on confirmation.

``prepare`` / ``confirm`` run before the HTTP response starts (a bad request, an unknown item or a
refused confirmation is a plain JSON error). ``stream`` runs after and never raises: every failure
ends it with a fatal ``StreamError``. The loop offers only the tools the principal may use, runs
read tools at once and stops at the first tool that needs the person's confirmation: it stores a
pending call and ends the turn. Only ``confirm`` runs that tool, with the confirming person's own
principal, then resumes the loop. Prompts, messages and tool output are never logged.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, cast

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.config_keys import CHAT_CONFIRM_TTL_SECONDS, CHAT_MAX_TOOL_CALLS_PER_TURN
from cashapp.domain.principal import Principal
from cashapp.integrations.llm.base import (
    LlmClients,
    LlmError,
    LlmErrorCode,
    ToolCallingLlm,
    ToolTurnComplete,
    ToolTurnDelta,
    ToolTurnRequest,
)
from cashapp.services.chat.audit import ChatToolAudit, ToolAuditEntry
from cashapp.services.chat.context import ChatContextBuilder, fit_context, fit_text
from cashapp.services.chat.errors import (
    ChatForbidden,
    ChatInvalid,
    ToolCallConflict,
    ToolCallNotFound,
)
from cashapp.services.chat.events import (
    ChatContextRef,
    ChatEvent,
    ConfirmRequired,
    Done,
    StopReason,
    StreamError,
    TextDelta,
    ToolFinished,
    ToolProgress,
    ToolStarted,
)
from cashapp.services.chat.prompts import (
    PROMPT_VERSION,
    TOOL_OUTPUT_CLOSE,
    TOOL_OUTPUT_OPEN,
    PromptKey,
    render_system,
)
from cashapp.services.chat.runner import ToolOutcome, ToolRunner
from cashapp.services.chat.threads import (
    AWAITING_TEXT,
    PendingInfo,
    ThreadInfo,
    ThreadService,
    ThreadView,
    tool_result_block,
)
from cashapp.services.chat.tools.registry import (
    Confirmation,
    ToolContext,
    ToolGroup,
    ToolRegistry,
    ToolServices,
    ToolSpec,
    UnknownTool,
)
from cashapp.services.config import RuntimeConfig

logger = logging.getLogger(__name__)

MAX_TOKENS: Final = 16000
MAX_MESSAGE_CHARS: Final = 4000
MAX_CONTEXT_CHARS: Final = 24000
TOOL_RESULT_MAX_CHARS: Final = 12000
DEFAULT_EFFORT: Final = "low"

ERROR_MESSAGES: Final[dict[str, str]] = {
    "TIMEOUT": "The assistant didn't answer (timeout).",
    "LLM_UNAVAILABLE": "The assistant is unavailable right now.",
    "REFUSED": "The assistant declined to answer.",
    "INTERNAL_ERROR": "The assistant hit an unexpected error.",
}

__all__ = [
    "MAX_CONTEXT_CHARS",
    "MAX_MESSAGE_CHARS",
    "MAX_TOKENS",
    "TOOL_RESULT_MAX_CHARS",
    "ChatService",
    "PreparedChat",
    "PreparedConfirm",
    "ThreadDescription",
    "ThreadMessageOut",
    "ThreadToolOut",
    "ToolGroupInfo",
    "ToolInfo",
]


@dataclass(frozen=True, slots=True)
class _Session:
    """Everything one request needs to talk to the model; holds no database session."""

    client: ToolCallingLlm
    model_id: str
    timeout_s: float
    effort: str
    system: str
    thread: ThreadInfo
    principal: Principal
    groups: tuple[ToolGroup, ...] | None
    max_calls: int


@dataclass(frozen=True, slots=True)
class PreparedChat:
    session: _Session


@dataclass(frozen=True, slots=True)
class PreparedConfirm:
    session: _Session
    pending: PendingInfo
    reason: str
    expected_version: int | None


@dataclass(slots=True)
class _Turn:
    """Counters across the loop of one HTTP response."""

    started: float = field(default_factory=time.monotonic)
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    last_message_id: int = 0


@dataclass(frozen=True, slots=True)
class _ToolResult:
    """Internal: one tool_result block, plus how the call ended the turn."""

    block: dict[str, Any]
    awaiting: bool = False
    over_limit: bool = False


class _FatalError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL_ERROR"])


@dataclass(frozen=True, slots=True)
class ToolInfo:
    name: str
    description: str
    mutating: bool
    allowed: bool


@dataclass(frozen=True, slots=True)
class ToolGroupInfo:
    group: ToolGroup
    allowed: bool
    tools: list[ToolInfo]


@dataclass(frozen=True, slots=True)
class ThreadToolOut:
    call_id: str
    tool: str
    group: ToolGroup
    summary: str
    ok: bool
    duration_ms: int
    status: str  # done | failed | waiting | cancelled | expired
    result_card: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ThreadMessageOut:
    id: int
    seq: int
    role: str
    text: str
    tools: list[ThreadToolOut]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ThreadDescription:
    thread: ThreadInfo
    messages: list[ThreadMessageOut]
    pending: PendingInfo | None


class ChatService:
    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        llm: LlmClients,
        runtime: RuntimeConfig,
        registry: ToolRegistry,
        services: ToolServices,
        clock: Clock | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._llm = llm
        self._runtime = runtime
        self._registry = registry
        self._services = services
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._context = ChatContextBuilder(self._clock)
        self._threads = ThreadService(uow_factory, self._clock)
        self._runner = ToolRunner(registry, uow_factory, self._clock)

    # --- before the stream ----------------------------------------------------------------

    async def prepare(
        self,
        principal: Principal,
        *,
        thread_id: int | None,
        key: PromptKey,
        ref: ChatContextRef,
        message: str,
        tool_groups: Collection[ToolGroup] | None,
    ) -> PreparedChat:
        """Validate the turn, open or reopen the thread, store the message, build the session.

        Raises ``ChatInvalid`` / ``ChatNotFound`` / ``ThreadNotFound``.
        """
        if not message.strip() or len(message) > MAX_MESSAGE_CHARS:
            raise ChatInvalid(
                "validation_error", f"The message must be 1 to {MAX_MESSAGE_CHARS} characters"
            )
        thread: ThreadInfo | None = None
        if thread_id is not None:
            thread = await self._threads.get_owned(principal, thread_id)
            if thread.prompt_key != key.value:
                raise ChatInvalid(
                    "chat_prompt_mismatch", "A follow-up must keep the thread's system_prompt_key"
                )
            ref = thread.context
        else:
            self._validate_context(key, ref)
        session = await self._session(
            principal,
            thread,
            key=key,
            ref=ref,
            groups=tool_groups,
            message=message,
        )
        await self._threads.supersede_open(session.thread.id)
        await self._threads.append(
            session.thread.id, "user", [{"type": "text", "text": message}], message
        )
        return PreparedChat(session)

    async def confirm(
        self,
        principal: Principal,
        call_id: str,
        reason: str,
        expected_version: int | None,
    ) -> PreparedConfirm:
        """Decide a pending call as confirmed. Raises before the stream starts.

        Order: unknown (404), someone else's (409), permission re-checked from the caller's token
        (403), already decided (409), expired (409).
        """
        pending = await self._threads.peek_pending(principal, call_id)
        spec = self._spec_or_missing(pending)
        if not principal.can(spec.permission):
            raise ChatForbidden(spec.permission.value)
        try:
            claimed = await self._threads.claim_pending(principal, call_id, reason)
        except ToolCallConflict as exc:
            if exc.code == "tool_call_expired":
                await self._audit_decision(principal, pending, spec, "EXPIRED", "confirm")
            raise
        thread = await self._threads.get_owned(principal, claimed.thread_id)
        key = PromptKey(thread.prompt_key)
        session = await self._session(
            principal, thread, key=key, ref=thread.context, groups=None, message=None
        )
        version = expected_version
        if version is None:
            preview_version = claimed.preview.get("expected_version")
            version = preview_version if isinstance(preview_version, int) else None
        return PreparedConfirm(session, claimed, reason, version)

    async def cancel(self, principal: Principal, call_id: str) -> str:
        """Decline a pending call; nothing runs. Returns the call id."""
        pending = await self._threads.peek_pending(principal, call_id)
        spec = self._spec_or_missing(pending)
        await self._threads.cancel_pending(principal, call_id)
        await self._audit_decision(principal, pending, spec, "CANCELLED", "cancel")
        return call_id

    def list_tools(self, principal: Principal) -> list[ToolGroupInfo]:
        """Every registered group with each tool and whether this principal may use it."""
        grouped: dict[ToolGroup, list[ToolInfo]] = {group: [] for group in ToolGroup}
        for spec in self._registry.all():
            grouped[spec.group].append(
                ToolInfo(spec.name, spec.description, spec.mutating, principal.can(spec.permission))
            )
        return [
            ToolGroupInfo(group, any(t.allowed for t in tools), tools)
            for group, tools in sorted(grouped.items(), key=lambda item: item[0].value)
            if tools
        ]

    async def get_thread(self, principal: Principal, thread_id: int) -> ThreadDescription:
        view = await self._threads.view(principal, thread_id)
        return self._describe(view)

    # --- helpers before the stream --------------------------------------------------------

    @staticmethod
    def _validate_context(key: PromptKey, ref: ChatContextRef) -> None:
        if key is PromptKey.ITEM and (ref.kind != "item" or ref.item_id is None):
            raise ChatInvalid("validation_error", "context.id is required for an item chat")
        if key is PromptKey.MATCHING and ref.kind == "item":
            raise ChatInvalid(
                "chat_context_not_allowed", "The matching assistant does not take an item context"
            )
        if key is PromptKey.FLOW and ref.kind == "item":
            raise ChatInvalid("validation_error", "A flow chat takes no item context")

    def _spec_or_missing(self, pending: PendingInfo) -> ToolSpec[Any, Any]:
        try:
            return self._registry.get(pending.tool)
        except UnknownTool as exc:
            raise ToolCallNotFound(pending.call_id) from exc

    async def _context_json(self, key: PromptKey, ref: ChatContextRef) -> str | None:
        async with self._uow_factory() as uow:
            if ref.kind == "item" and ref.item_id is not None:
                doc = await self._context.item_context(uow, ref.item_id)
            elif key is PromptKey.MATCHING:
                doc = await self._context.aggregates_context(uow)
            elif ref.kind == "flow" or key is PromptKey.FLOW:
                doc = await self._context.flow_context(uow)
            else:
                return None
        return fit_context(doc, MAX_CONTEXT_CHARS)

    async def _session(
        self,
        principal: Principal,
        thread: ThreadInfo | None,
        *,
        key: PromptKey,
        ref: ChatContextRef,
        groups: Collection[ToolGroup] | None,
        message: str | None,
    ) -> _Session:
        context_json = await self._context_json(key, ref)
        snapshot = await self._runtime.snapshot()
        role = snapshot.models().workhorse
        client = self._llm.workhorse.with_model(role.model_id)
        model_id = client.model_id
        if not isinstance(client, ToolCallingLlm):
            raise ChatInvalid("llm_unavailable", "The assistant is unavailable right now.")
        if thread is None:
            thread = await self._threads.create(principal, key.value, ref, message or "")
        return _Session(
            client=client,
            model_id=model_id,
            timeout_s=float(role.timeout_s),
            effort=role.effort or DEFAULT_EFFORT,
            system=render_system(key, context_json),
            thread=thread,
            principal=principal,
            groups=tuple(groups) if groups is not None else None,
            max_calls=snapshot.get(CHAT_MAX_TOOL_CALLS_PER_TURN),
        )

    async def _audit_decision(
        self,
        principal: Principal,
        pending: PendingInfo,
        spec: ToolSpec[Any, Any],
        outcome: str,
        phase: str,
    ) -> None:
        entry = ToolAuditEntry(
            at=self._clock.now(),
            thread_id=pending.thread_id,
            call_id=pending.call_id,
            tool=spec.name,
            audit_label=spec.audit_label,
            actor_subject=principal.subject,
            actor_name=principal.display_name,
            input_summary=spec.name,
            outcome=outcome,
            error_code=None,
            duration_ms=0,
            phase=phase,
        )
        async with self._uow_factory() as uow:
            await ChatToolAudit.record(uow, entry)
            await uow.commit()

    # --- the stream -----------------------------------------------------------------------

    async def stream(self, prepared: PreparedChat | PreparedConfirm) -> AsyncGenerator[ChatEvent]:
        """Events for one response; a failure ends it with a fatal ``StreamError``. Never raises."""
        session = prepared.session
        turn = _Turn()
        try:
            if isinstance(prepared, PreparedConfirm):
                async for event in self._run_confirmed(prepared, turn):
                    yield event
            async for event in self._loop(session, turn):
                yield event
        except _FatalError as exc:
            yield StreamError(exc.code, exc.message, session.thread.id, fatal=True)
        except LlmError as exc:
            code = "REFUSED" if exc.code is LlmErrorCode.LLM_REFUSAL else "LLM_UNAVAILABLE"
            logger.warning("Chat stream failed", extra={"chat_error": exc.code.value})
            yield StreamError(code, ERROR_MESSAGES[code], session.thread.id, fatal=True)
        except Exception as exc:
            logger.warning("Chat stream failed", extra={"chat_error": type(exc).__name__})
            yield StreamError(
                "INTERNAL_ERROR", ERROR_MESSAGES["INTERNAL_ERROR"], session.thread.id, fatal=True
            )

    def _done(self, session: _Session, turn: _Turn, stop: StopReason) -> Done:
        return Done(
            thread_id=session.thread.id,
            message_id=turn.last_message_id,
            stop=stop,
            model_id=session.model_id,
            latency_ms=int((time.monotonic() - turn.started) * 1000),
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
        )

    async def _loop(self, session: _Session, turn: _Turn) -> AsyncGenerator[ChatEvent]:
        offered = self._registry.for_principal(session.principal, session.groups)
        offered_names = {spec.name for spec in offered}
        tools = tuple(self._registry.anthropic_tools(session.principal, session.groups))
        thread_id = session.thread.id
        work_item_id = session.thread.context.item_id
        while True:
            messages = await self._threads.messages_for_model(thread_id)
            request = ToolTurnRequest(
                system=session.system,
                messages=tuple(messages),
                tools=tools,
                max_tokens=MAX_TOKENS,
                timeout_s=session.timeout_s,
                purpose="chat.workhorse",
                effort=session.effort,
                work_item_id=work_item_id,
                prompt_version=PROMPT_VERSION,
            )
            complete: ToolTurnComplete | None = None
            async for item in self._model_turn(session, request):
                if isinstance(item, ToolTurnComplete):
                    complete = item
                else:
                    yield item
            if complete is None:
                raise _FatalError("INTERNAL_ERROR")
            turn.input_tokens += complete.usage.input_tokens
            turn.output_tokens += complete.usage.output_tokens
            content = [dict(block) for block in complete.content]
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            if complete.stop_reason == "max_tokens" and tool_uses:
                # A tool call cut off mid-input is never run and never stored (the history would
                # hold a tool_use without a result).
                raise _FatalError(
                    "INTERNAL_ERROR", "The reply was cut off before the tool call ended."
                )
            text = "".join(str(b.get("text", "")) for b in content if b.get("type") == "text")
            turn.last_message_id = await self._threads.append(
                thread_id, "assistant", content, text or None
            )
            if complete.stop_reason != "tool_use" or not tool_uses:
                yield self._done(session, turn, "end_turn")
                return

            results: list[dict[str, Any]] = []
            awaiting = False
            over_limit = False
            for block in tool_uses:
                call_id = str(block["id"])
                outcome_events = self._handle_tool_use(
                    session, turn, block, offered_names, allow_pending=not awaiting
                )
                async for event in outcome_events:
                    if isinstance(event, _ToolResult):
                        results.append(event.block)
                        awaiting = awaiting or event.awaiting
                        over_limit = over_limit or event.over_limit
                    else:
                        yield event
                if not any(r["tool_use_id"] == call_id for r in results):
                    results.append(tool_result_block(call_id, "no result", is_error=True))
            await self._threads.append(thread_id, "tool_results", results)
            if awaiting:
                yield self._done(session, turn, "awaiting_confirmation")
                return
            if over_limit:
                yield StreamError(
                    "TOOL_LIMIT",
                    "The assistant reached its tool-call limit for this reply.",
                    thread_id,
                )
                yield self._done(session, turn, "tool_limit")
                return

    async def _model_turn(
        self, session: _Session, request: ToolTurnRequest
    ) -> AsyncGenerator[TextDelta | ToolTurnComplete]:
        deadline = time.monotonic() + session.timeout_s
        events = aiter(session.client.stream_tool_turn(request))
        try:
            while True:
                try:
                    async with asyncio.timeout(max(deadline - time.monotonic(), 0.0)):
                        event = await anext(events)
                except StopAsyncIteration:
                    return
                except TimeoutError as exc:
                    raise _FatalError("TIMEOUT") from exc
                if isinstance(event, ToolTurnDelta):
                    yield TextDelta(event.text)
                else:
                    yield event
        finally:
            if isinstance(events, AsyncGenerator):
                await events.aclose()

    async def _handle_tool_use(
        self,
        session: _Session,
        turn: _Turn,
        block: dict[str, Any],
        offered_names: set[str],
        *,
        allow_pending: bool,
    ) -> AsyncGenerator[ChatEvent | _ToolResult]:
        call_id = str(block["id"])
        thread_id = session.thread.id
        try:
            spec = self._registry.get_by_wire_name(str(block["name"]))
        except UnknownTool:
            yield StreamError(
                "UNKNOWN_TOOL",
                "The assistant asked for a tool that does not exist.",
                thread_id,
                call_id,
            )
            yield _ToolResult(
                tool_result_block(call_id, "UNKNOWN_TOOL: no such tool", is_error=True)
            )
            return
        if turn.calls >= session.max_calls:
            yield _ToolResult(
                tool_result_block(
                    call_id, "TOOL_LIMIT: too many tool calls this turn", is_error=True
                ),
                over_limit=True,
            )
            return
        turn.calls += 1
        raw = block.get("input", {})
        ctx_args = (session, spec, call_id)
        yield ToolStarted(call_id, spec.name, spec.group, _start_summary(spec, raw), spec.mutating)

        if spec.confirm_required:
            if not allow_pending:
                yield _failed_event(spec, call_id, 0, "CONFLICT", "One change per message.")
                yield _ToolResult(
                    tool_result_block(
                        call_id,
                        "CONFLICT: only one change can wait for confirmation per message. "
                        "Propose this one after the first is decided.",
                        is_error=True,
                    )
                )
                return
            outcome = await self._runner.execute(
                spec,
                self._ctx(*ctx_args, confirmation=None, queue=None),
                raw,
                allowed=spec.name in offered_names,
                preview_only=True,
            )
            if not outcome.ok or outcome.preview is None or outcome.parsed_input is None:
                yield self._finished(spec, call_id, outcome)
                yield _ToolResult(_result_block(call_id, outcome))
                return
            ttl = await self._runtime.get(CHAT_CONFIRM_TTL_SECONDS)
            expires_at = self._clock.now() + timedelta(seconds=ttl)
            await self._threads.create_pending(
                thread_id,
                session.principal,
                call_id,
                spec.name,
                outcome.parsed_input.model_dump(mode="json"),
                outcome.preview.model_dump(mode="json"),
                expires_at,
            )
            yield ConfirmRequired(call_id, spec.name, outcome.preview, expires_at)
            yield _ToolResult(tool_result_block(call_id, AWAITING_TEXT), awaiting=True)
            return

        final: ToolOutcome | None = None
        async for item in self._run_with_progress(
            session, spec, call_id, raw, None, "run", allowed=spec.name in offered_names
        ):
            if isinstance(item, ToolProgress):
                yield item
            else:
                final = item
        if final is None:
            raise _FatalError("INTERNAL_ERROR")
        if final.error_code == "FORBIDDEN":
            yield StreamError("FORBIDDEN", final.message or "Not allowed.", thread_id, call_id)
        yield self._finished(spec, call_id, final)
        yield _ToolResult(_result_block(call_id, final))

    async def _run_confirmed(
        self, prepared: PreparedConfirm, turn: _Turn
    ) -> AsyncGenerator[ChatEvent]:
        pending = prepared.pending
        session = prepared.session
        spec = self._registry.get(pending.tool)
        call_id = pending.call_id
        confirmation = Confirmation(call_id, prepared.reason, prepared.expected_version)
        try:
            summary = (
                spec.summarize_input(spec.input_model.model_validate(pending.input))
                if (spec.summarize_input is not None)
                else spec.name
            )
        except Exception:
            summary = spec.name
        yield ToolStarted(call_id, spec.name, spec.group, summary[:200], True)
        final: ToolOutcome | None = None
        async for item in self._run_with_progress(
            session, spec, call_id, pending.input, confirmation, "confirm", allowed=True
        ):
            if isinstance(item, ToolProgress):
                yield item
            else:
                final = item
        if final is None:
            raise _FatalError("INTERNAL_ERROR")
        yield self._finished(spec, call_id, final)
        block = _result_block(call_id, final)
        await self._threads.complete_tool_result(
            session.thread.id, call_id, str(block["content"]), is_error=not final.ok
        )
        if not final.ok:
            await self._threads.mark_failed(call_id)
        turn.calls += 1

    def _ctx(
        self,
        session: _Session,
        spec: ToolSpec[Any, Any],
        call_id: str,
        *,
        confirmation: Confirmation | None,
        queue: "asyncio.Queue[ToolProgress] | None",
    ) -> ToolContext:
        del spec

        async def progress(done: int, total: int) -> None:
            if queue is not None:
                queue.put_nowait(ToolProgress(call_id, done, total))

        return ToolContext(
            principal=session.principal,
            uow_factory=self._uow_factory,
            clock=self._clock,
            services=self._services,
            thread_id=session.thread.id,
            call_id=call_id,
            confirmation=confirmation,
            progress=progress,
        )

    async def _run_with_progress(
        self,
        session: _Session,
        spec: ToolSpec[Any, Any],
        call_id: str,
        raw: object,
        confirmation: Confirmation | None,
        phase: str,
        *,
        allowed: bool,
    ) -> AsyncGenerator[ToolProgress | ToolOutcome]:
        """Run a tool, relaying its progress as it arrives; the last item is the outcome."""
        queue: asyncio.Queue[ToolProgress] = asyncio.Queue()
        ctx = self._ctx(session, spec, call_id, confirmation=confirmation, queue=queue)
        task = asyncio.ensure_future(
            self._runner.execute(spec, ctx, raw, phase=phase, allowed=allowed)
        )
        try:
            while not task.done():
                getter = asyncio.ensure_future(queue.get())
                await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter.done():
                    yield getter.result()
                else:
                    getter.cancel()
            while not queue.empty():
                yield queue.get_nowait()
            yield task.result()
        finally:
            if not task.done():
                task.cancel()

    @staticmethod
    def _finished(spec: ToolSpec[Any, Any], call_id: str, outcome: ToolOutcome) -> ToolFinished:
        return ToolFinished(
            call_id=call_id,
            tool=spec.name,
            duration_ms=outcome.duration_ms,
            ok=outcome.ok,
            summary=outcome.summary,
            result_card=outcome.card,
            error_code=outcome.error_code,
            error_message=outcome.message,
        )

    # --- thread view ----------------------------------------------------------------------

    def _describe(self, view: ThreadView) -> ThreadDescription:
        now = self._clock.now()
        pending_by_call = {p.call_id: p for p in view.pending}
        runs_by_call: dict[str, list[Any]] = {}
        for run in view.runs:
            runs_by_call.setdefault(run.call_id, []).append(run)
        messages: list[ThreadMessageOut] = []
        for row in view.messages:
            if row.role == "tool_results":
                continue
            tools: list[ThreadToolOut] = []
            raw_content: Any = row.content
            if row.role == "assistant" and isinstance(raw_content, list):
                for raw_block in cast("list[Any]", raw_content):
                    if not isinstance(raw_block, dict):
                        continue
                    block = cast("dict[str, Any]", raw_block)
                    if block.get("type") != "tool_use":
                        continue
                    try:
                        spec = self._registry.get_by_wire_name(str(block["name"]))
                    except UnknownTool:
                        continue
                    call_id = str(block["id"])
                    tools.append(
                        _thread_tool(
                            spec,
                            call_id,
                            runs_by_call.get(call_id, []),
                            pending_by_call.get(call_id),
                            now,
                        )
                    )
            messages.append(
                ThreadMessageOut(
                    id=row.id,
                    seq=row.seq,
                    role="assistant" if row.role == "assistant" else "user",
                    text=row.display_text or "",
                    tools=tools,
                    created_at=row.created_at,
                )
            )
        open_pending = next(
            (p for p in view.pending if p.status == "PENDING" and p.expires_at > now), None
        )
        return ThreadDescription(view.thread, messages, open_pending)


def _start_summary(spec: ToolSpec[Any, Any], raw: object) -> str:
    if spec.summarize_input is None:
        return spec.name
    try:
        return spec.summarize_input(spec.input_model.model_validate(raw))[:200]
    except Exception:
        return spec.name


def _failed_event(
    spec: ToolSpec[Any, Any], call_id: str, duration_ms: int, code: str, message: str
) -> ToolFinished:
    return ToolFinished(
        call_id=call_id,
        tool=spec.name,
        duration_ms=duration_ms,
        ok=False,
        error_code=code,
        error_message=message,
    )


def _result_block(call_id: str, outcome: ToolOutcome) -> dict[str, Any]:
    """The tool_result for the model: output as clipped data, or an error line."""
    if outcome.ok and outcome.output is not None:
        body = fit_text(outcome.output.model_dump_json(), TOOL_RESULT_MAX_CHARS)
        return tool_result_block(call_id, f"{TOOL_OUTPUT_OPEN}{body}{TOOL_OUTPUT_CLOSE}")
    message = json.dumps(outcome.message or "failed")
    return tool_result_block(call_id, f"{outcome.error_code or 'ERROR'}: {message}", is_error=True)


def _thread_tool(
    spec: ToolSpec[Any, Any],
    call_id: str,
    runs: list[Any],
    pending: PendingInfo | None,
    now: Any,
) -> ThreadToolOut:
    done_runs = [r for r in runs if r.phase in {"run", "confirm"}]
    last = done_runs[-1] if done_runs else None
    status = "failed"
    ok = False
    if spec.confirm_required and pending is not None:
        if pending.status == "PENDING":
            status = "expired" if pending.expires_at <= now else "waiting"
        elif pending.status in {"CANCELLED", "SUPERSEDED"}:
            status = "cancelled"
        elif pending.status == "EXPIRED":
            status = "expired"
        else:  # CONFIRMED | FAILED: the confirm run decides
            confirm_runs = [r for r in runs if r.phase == "confirm"]
            last = confirm_runs[-1] if confirm_runs else None
            ok = last is not None and last.outcome == "OK"
            status = "done" if ok else "failed"
    elif last is not None:
        ok = last.outcome == "OK"
        status = "done" if ok else "failed"
    return ThreadToolOut(
        call_id=call_id,
        tool=spec.name,
        group=spec.group,
        summary=(last.summary if last is not None and last.summary else spec.audit_label),
        ok=ok,
        duration_ms=last.duration_ms if last is not None else 0,
        status=status,
        result_card=last.result_card if last is not None else None,
    )
