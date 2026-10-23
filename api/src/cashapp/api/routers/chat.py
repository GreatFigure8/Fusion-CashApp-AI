"""``POST /chat/stream``: the one LLM chat endpoint (Server-Sent Events).

Authorization and validation run before the stream starts, so those failures are plain JSON in the
single error shape. After it starts, every failure is a ``stream-error`` frame (never ``error``).
"""

from collections.abc import AsyncGenerator
from typing import Annotated, Final

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse, ServerSentEvent

from cashapp.api.config_deps import RuntimeConfigDep
from cashapp.api.deps import UowFactoryDep
from cashapp.api.errors import ERROR_RESPONSES, ApiError
from cashapp.api.llm_deps import LlmClientsDep
from cashapp.api.schemas.chat import (
    ActionData,
    ChatStreamEventsDoc,
    ChatStreamIn,
    DoneData,
    StreamErrorData,
    TokenData,
    UsageData,
)
from cashapp.auth.deps import require_permission
from cashapp.domain.principal import Permission, Principal
from cashapp.services.chat import (
    ActionEvent,
    ChatEvent,
    ChatInvalid,
    ChatNotFound,
    ChatService,
    DoneEvent,
    StreamErrorEvent,
    TokenEvent,
)

PING_SECONDS: Final = 15

router = APIRouter(tags=["chat"], responses=ERROR_RESPONSES)

ChatUserDep = Annotated[Principal, Depends(require_permission(Permission.CHAT_USE))]


def get_chat_service(
    uow_factory: UowFactoryDep, llm: LlmClientsDep, runtime: RuntimeConfigDep
) -> ChatService:
    """The chat service; tests override this dependency."""
    return ChatService(uow_factory=uow_factory, llm=llm, runtime=runtime)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def _frame(event: ChatEvent, number: int) -> ServerSentEvent:
    match event:
        case TokenEvent():
            name, data = "token", TokenData(text=event.text).model_dump_json()
        case ActionEvent():
            name = "action"
            data = ActionData(
                id=event.id, label=event.label, args=dict(event.args)
            ).model_dump_json()
        case DoneEvent():
            name = "done"
            data = DoneData(
                usage=UsageData(
                    model_id=event.model_id,
                    latency_ms=event.latency_ms,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                )
            ).model_dump_json()
        case StreamErrorEvent():
            name = "stream-error"
            data = StreamErrorData.model_validate(
                {"code": event.code, "message": event.message}
            ).model_dump_json()
    return ServerSentEvent(data=data, event=name, id=str(number))


@router.post(
    "/chat/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": (
                "Server-Sent Events: `token`, `action`, `done` or `stream-error` frames, each "
                "with a monotonic `id`."
            ),
            "model": ChatStreamEventsDoc,
        }
    },
)
async def chat_stream(
    body: ChatStreamIn, principal: ChatUserDep, service: ChatServiceDep
) -> EventSourceResponse:
    try:
        prepared = await service.prepare(
            principal,
            body.context.to_ref(),
            body.system_prompt_key,
            body.turns(),
            body.allowed_actions,
        )
    except ChatNotFound as exc:
        raise ApiError(404, "item_not_found", f"Item {exc.item_id} not found") from exc
    except ChatInvalid as exc:
        raise ApiError(422, exc.code, exc.message) from exc

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

    return EventSourceResponse(frames(), ping=PING_SECONDS)
