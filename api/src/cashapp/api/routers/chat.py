"""The assistant chat: ``POST /chat/stream`` (the one LLM chat endpoint) and its tool endpoints.

Authorization and validation run before a stream starts, so those failures are plain JSON in the
single error shape. After it starts, every failure is an ``error`` frame. Frames are
``id:`` / ``event:`` / ``data:`` with a 15 second comment heartbeat; the response disables
proxy buffering. The assistant proposes changes as tool calls; only the confirm endpoint, with the
caller's own token, runs one.
"""

from collections.abc import AsyncGenerator
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse, ServerSentEvent

from cashapp.api.chat_deps import ToolRegistryDep, ToolServicesDep
from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.llm_deps import LlmClientsDep
from cashapp.api.schemas.chat import (
    CancelOut,
    ChatStreamEventsDoc,
    ChatStreamIn,
    ChatThreadOut,
    ConfirmIn,
    ConfirmRequiredData,
    DoneData,
    StreamErrorData,
    TextDeltaData,
    ToolErrorData,
    ToolFinishedData,
    ToolGroupOut,
    ToolProgressData,
    ToolStartedData,
    UsageData,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.chat import (
    ChatEvent,
    ChatForbidden,
    ChatInvalid,
    ChatNotFound,
    ChatService,
    ConfirmRequired,
    Done,
    PreparedChat,
    PreparedConfirm,
    StreamError,
    TextDelta,
    ThreadNotFound,
    ToolCallConflict,
    ToolCallNotFound,
    ToolFinished,
    ToolProgress,
    ToolStarted,
)
from cashapp.services.chat.errors import ChatError

PING_SECONDS: Final = 15
STREAM_HEADERS: Final = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}

router = APIRouter(tags=["chat"], responses=ERROR_RESPONSES)

ChatUserDep = Annotated[Principal, Depends(require_permission(Permission.CHAT_USE))]


def get_chat_service(
    uow_factory: UowFactoryDep,
    llm: LlmClientsDep,
    runtime: RuntimeConfigDep,
    registry: ToolRegistryDep,
    services: ToolServicesDep,
) -> ChatService:
    """The chat service; tests override this dependency."""
    return ChatService(
        uow_factory=uow_factory, llm=llm, runtime=runtime, registry=registry, services=services
    )


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def _chat_api_error(exc: ChatError) -> ApiError:
    """The pre-stream refusals, in the single error shape."""
    if isinstance(exc, ChatNotFound):
        return ApiError(404, "item_not_found", f"Item {exc.item_id} not found")
    if isinstance(exc, ThreadNotFound):
        return ApiError(404, "thread_not_found", f"Thread {exc.thread_id} not found")
    if isinstance(exc, ToolCallNotFound):
        return ApiError(404, "tool_call_not_found", "That tool call was not found")
    if isinstance(exc, ToolCallConflict):
        return ApiError(
            409, exc.code, _CONFLICT_MESSAGES.get(exc.code, "That call cannot be decided")
        )
    if isinstance(exc, ChatForbidden):
        return ApiError(
            403,
            "forbidden",
            f"Missing permission {exc.permission}",
            details=[{"permission": exc.permission}],
        )
    if isinstance(exc, ChatInvalid):
        return ApiError(422, exc.code, exc.message)
    return ApiError(400, "chat_error", str(exc))


_CONFLICT_MESSAGES: Final = {
    "tool_call_expired": "That proposal expired before it was confirmed",
    "tool_call_not_yours": "That proposal belongs to someone else",
    "tool_call_decided": "That proposal was already decided",
}


def _frame(event: ChatEvent, number: int) -> ServerSentEvent:
    match event:
        case TextDelta():
            name, data = "text_delta", TextDeltaData(text=event.text).model_dump_json()
        case ToolStarted():
            name = "tool_started"
            data = ToolStartedData(
                call_id=event.call_id,
                tool=event.tool,
                group=event.group,
                summary=event.summary,
                mutating=event.mutating,
            ).model_dump_json()
        case ToolProgress():
            name = "tool_progress"
            data = ToolProgressData(
                call_id=event.call_id, done=event.done, total=event.total
            ).model_dump_json()
        case ToolFinished():
            name = "tool_finished"
            data = ToolFinishedData.model_validate(
                {
                    "call_id": event.call_id,
                    "tool": event.tool,
                    "duration_ms": event.duration_ms,
                    "ok": event.ok,
                    "summary": event.summary,
                    "result_card": event.result_card,
                    "error": ToolErrorData(
                        code=event.error_code or "ERROR", message=event.error_message or ""
                    )
                    if not event.ok
                    else None,
                }
            ).model_dump_json()
        case ConfirmRequired():
            name = "confirm_required"
            data = ConfirmRequiredData(
                call_id=event.call_id,
                tool=event.tool,
                preview=event.preview,
                expires_at=event.expires_at,
            ).model_dump_json()
        case StreamError():
            name = "error"
            data = StreamErrorData.model_validate(
                {
                    "code": event.code,
                    "message": event.message,
                    "call_id": event.call_id,
                    "fatal": event.fatal,
                    "thread_id": event.thread_id,
                }
            ).model_dump_json()
        case Done():
            name = "done"
            data = DoneData(
                thread_id=event.thread_id,
                message_id=event.message_id,
                stop=event.stop,
                usage=UsageData(
                    model_id=event.model_id,
                    latency_ms=event.latency_ms,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                ),
            ).model_dump_json()
    return ServerSentEvent(data=data, event=name, id=str(number))


def _stream_response(
    service: ChatService, prepared: PreparedChat | PreparedConfirm
) -> EventSourceResponse:
    async def frames() -> AsyncGenerator[ServerSentEvent, None]:
        events = service.stream(prepared)
        try:
            number = 0
            async for event in events:
                number += 1
                yield _frame(event, number)
        finally:
            # A client disconnect cancels this generator; closing the service generator in turn
            # closes the LLM stream.
            await events.aclose()

    return EventSourceResponse(frames(), ping=PING_SECONDS, headers=STREAM_HEADERS)


_STREAM_RESPONSE_DOC: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": (
            "Server-Sent Events: `text_delta`, `tool_started`, `tool_progress`, `tool_finished`, "
            "`confirm_required`, `error` or `done` frames, each with a monotonic `id`."
        ),
        "model": ChatStreamEventsDoc,
    }
}


@router.post("/chat/stream", response_class=EventSourceResponse, responses=_STREAM_RESPONSE_DOC)
async def chat_stream(
    body: ChatStreamIn, principal: ChatUserDep, service: ChatServiceDep
) -> EventSourceResponse:
    try:
        prepared = await service.prepare(
            principal,
            thread_id=body.thread_id,
            key=body.system_prompt_key,
            ref=body.context.to_ref(),
            message=body.message,
            tool_groups=body.tool_groups,
        )
    except ChatError as exc:
        raise _chat_api_error(exc) from exc
    return _stream_response(service, prepared)


@router.post(
    "/chat/tool-calls/{call_id}/confirm",
    response_class=EventSourceResponse,
    responses=_STREAM_RESPONSE_DOC,
)
async def confirm_tool_call(
    call_id: str, body: ConfirmIn, principal: ChatUserDep, service: ChatServiceDep
) -> EventSourceResponse:
    try:
        prepared = await service.confirm(principal, call_id, body.reason, body.expected_version)
    except ChatError as exc:
        raise _chat_api_error(exc) from exc
    return _stream_response(service, prepared)


@router.post("/chat/tool-calls/{call_id}/cancel", response_model=CancelOut)
async def cancel_tool_call(
    call_id: str, principal: ChatUserDep, service: ChatServiceDep
) -> CancelOut:
    try:
        await service.cancel(principal, call_id)
    except ChatError as exc:
        raise _chat_api_error(exc) from exc
    return CancelOut(call_id=call_id)


@router.get("/chat/tools", response_model=list[ToolGroupOut])
async def list_chat_tools(principal: ChatUserDep, service: ChatServiceDep) -> list[ToolGroupOut]:
    return [ToolGroupOut.from_info(info) for info in service.list_tools(principal)]


@router.get("/chat/threads/{thread_id}", response_model=ChatThreadOut)
async def get_chat_thread(
    thread_id: int, principal: ChatUserDep, service: ChatServiceDep
) -> ChatThreadOut:
    try:
        described = await service.get_thread(principal, thread_id)
    except ChatError as exc:
        raise _chat_api_error(exc) from exc
    return ChatThreadOut.from_description(described)
