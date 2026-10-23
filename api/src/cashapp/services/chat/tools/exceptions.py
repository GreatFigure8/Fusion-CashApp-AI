"""Exception tools: list and inspect stuck items, and requeue one the person has dequeued."""

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm.exc import StaleDataError

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import Permission
from cashapp.domain.stages import Stage
from cashapp.services.autofix.requeue import RequeueCommand, RequeueError, RequeueService
from cashapp.services.chat.context import ChatContextBuilder
from cashapp.services.chat.errors import ChatNotFound
from cashapp.services.chat.tools.cards import (
    CardStat,
    CardStatus,
    StateCard,
    TableCard,
    TableColumn,
    Tone,
)
from cashapp.services.chat.tools.registry import (
    ConfirmPreview,
    PreviewField,
    ToolContext,
    ToolError,
    ToolGroup,
    ToolSpec,
    who_line,
)
from cashapp.services.exceptions_query import ExceptionFilters, ExceptionsQueryService
from cashapp.services.locking import ItemNotFound, LockError, LockNotHeld, is_lock_live


def _tone_of_state(state: str) -> Tone:
    if state in {"FAILED", "ESCALATED"}:
        return "err"
    if state in {"DONE", "APPLIED"}:
        return "ok"
    return "muted"


# --- exceptions.list ----------------------------------------------------------------------


class ListIn(BaseModel):
    q: str | None = Field(default=None, max_length=200, description="Free-text search.")
    stage: Stage | None = Field(default=None, description="Only items at this pipeline stage.")
    error_code: ErrorCode | None = Field(default=None, description="Only items with this error.")
    page_size: int = Field(default=20, ge=1, le=50)


class ExceptionRowOut(BaseModel):
    item_id: int
    payer_name: str | None
    amount: str | None
    currency: str | None
    stage: str
    state: str
    error_code: str | None
    age_s: int


class ListOut(BaseModel):
    total: int
    items: list[ExceptionRowOut]


async def _list(ctx: ToolContext, args: ListIn) -> ListOut:
    service = await ctx.services.get(ExceptionsQueryService)
    filters = ExceptionFilters(
        q=args.q,
        stage=args.stage,
        error_codes=(args.error_code,) if args.error_code is not None else (),
        page=1,
        page_size=args.page_size,
    )
    async with ctx.uow_factory() as uow:
        page = await service.list(uow, filters, ctx.principal)
    return ListOut(
        total=page.total,
        items=[
            ExceptionRowOut(
                item_id=row.item.id,
                payer_name=row.item.payer_name,
                amount=str(row.item.payment_amount)
                if row.item.payment_amount is not None
                else None,
                currency=row.item.currency,
                stage=row.item.stage.value,
                state=row.item.state.value,
                error_code=row.item.last_error_code.value if row.item.last_error_code else None,
                age_s=row.age_s,
            )
            for row in page.items
        ],
    )


def _list_card(out: ListOut) -> TableCard:
    return TableCard(
        title="Exceptions",
        columns=[
            TableColumn(key="item", label="Item"),
            TableColumn(key="payer", label="Payer"),
            TableColumn(key="amount", label="Amount", numeric=True),
            TableColumn(key="stage", label="Stage"),
            TableColumn(key="error", label="Error"),
        ],
        rows=[
            {
                "item": f"WI-{i.item_id}",
                "payer": i.payer_name,
                "amount": f"{i.amount} {i.currency}" if i.amount is not None else None,
                "stage": i.stage,
                "error": i.error_code,
            }
            for i in out.items
        ],
        total=out.total,
        truncated=out.total > len(out.items),
    )


# --- exceptions.get -----------------------------------------------------------------------


class GetIn(BaseModel):
    item_id: int = Field(description="The work item number, without the WI- prefix.")


class GetOut(BaseModel):
    item: dict[str, Any]


async def _get(ctx: ToolContext, args: GetIn) -> GetOut:
    try:
        async with ctx.uow_factory() as uow:
            doc = await ChatContextBuilder(ctx.clock).item_context(uow, args.item_id)
    except ChatNotFound as exc:
        raise ToolError("NOT_FOUND", f"Item {args.item_id} was not found.", 404) from exc
    return GetOut(item=doc)


def _get_card(out: GetOut) -> StateCard:
    item = out.item
    state = str(item.get("state"))
    stats = [
        CardStat(label="Stage", value=str(item.get("stage"))),
        CardStat(label="Payer", value=str(item.get("payer_name") or "unknown")),
        CardStat(
            label="Amount",
            value=f"{item.get('payment_amount') or '?'} {item.get('currency') or ''}".strip(),
        ),
    ]
    if item.get("last_error_code"):
        stats.append(CardStat(label="Last error", value=str(item["last_error_code"])))
    lock = item.get("lock")
    return StateCard(
        title=str(item.get("wi")),
        status=CardStatus(
            label="locked" if lock else state.lower(),
            tone="locked" if lock else _tone_of_state(state),
        ),
        stats=stats,
        history_id=str(item.get("wi")),
    )


# --- exceptions.requeue -------------------------------------------------------------------


class RequeueIn(BaseModel):
    item_id: int = Field(description="The work item number, without the WI- prefix.")
    target_stage: Stage | None = Field(
        default=None, description="Stage to send it back to; omit to retry the current stage."
    )
    customer_number: str | None = Field(default=None, description="A customer number to pin.")
    receipt_id: int | None = Field(default=None, description="A Fusion receipt id to pin.")


class RequeueOut(BaseModel):
    item_id: int
    stage: str
    state: str


async def _requeue_preview(ctx: ToolContext, args: RequeueIn) -> ConfirmPreview:
    async with ctx.uow_factory() as uow:
        item = await uow.work_items.get(args.item_id)
    if item is None:
        raise ToolError("NOT_FOUND", f"Item {args.item_id} was not found.", 404)
    if not is_lock_live(item, ctx.clock.now()) or item.lock_owner != ctx.principal.subject:
        raise ToolError(
            "LOCK_REQUIRED",
            f"WI-{item.id} must be dequeued (locked) by you before it can be requeued. "
            "Ask the person to dequeue it in the exception workbench first.",
            409,
        )
    target = args.target_stage or item.stage
    details = [PreviewField(label="Item", value=f"WI-{item.id}")]
    if args.customer_number:
        details.append(PreviewField(label="Pin customer", value=args.customer_number))
    if args.receipt_id is not None:
        details.append(PreviewField(label="Pin receipt", value=str(args.receipt_id)))
    return ConfirmPreview(
        what=f"Requeue WI-{item.id} at {target.value}",
        before=f"{item.stage.value} / {item.state.value}, locked by you",
        after=f"{target.value} / PENDING, released to automation",
        who=who_line(ctx.principal),
        reason_prompt="What did you fix, and why is it ready to go again?",
        details=details,
    )


async def _requeue(ctx: ToolContext, args: RequeueIn) -> RequeueOut:
    confirmation = ctx.confirmation
    if confirmation is None:
        raise ToolError("CONFLICT", "The requeue was not confirmed. Nothing changed.", 409)
    service = await ctx.services.get(RequeueService)
    command = RequeueCommand(
        note=confirmation.reason,
        target_stage=args.target_stage,
        customer_number=args.customer_number,
        receipt_id=args.receipt_id,
    )
    try:
        async with ctx.uow_factory() as uow:
            result = await service.requeue(uow, args.item_id, command, ctx.principal)
            await uow.commit()
    except ItemNotFound as exc:
        raise ToolError("NOT_FOUND", f"Item {args.item_id} was not found.", 404) from exc
    except LockNotHeld as exc:
        raise ToolError(
            "LOCK_REQUIRED", "You no longer hold the lock on that item. Nothing changed.", 409
        ) from exc
    except (LockError, RequeueError) as exc:
        raise ToolError("CONFLICT", f"{exc} Nothing changed.", 409) from exc
    except StaleDataError as exc:
        raise ToolError("CONFLICT", "The item changed. Nothing changed.", 409) from exc
    return RequeueOut(item_id=result.item_id, stage=result.stage.value, state=result.state.value)


def _requeue_card(out: RequeueOut) -> StateCard:
    return StateCard(
        title=f"WI-{out.item_id}",
        status=CardStatus(label="requeued", tone="accent"),
        stats=[CardStat(label="Stage", value=out.stage), CardStat(label="State", value=out.state)],
        history_id=f"WI-{out.item_id}",
    )


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="exceptions.list",
        group=ToolGroup.EXCEPTIONS,
        description=(
            "List items stuck in the pipeline (the exception worklist), oldest first, with their "
            "stage, state and last error. Optionally filter by text, stage or error code."
        ),
        input_model=ListIn,
        output_model=ListOut,
        permission=Permission.ITEMS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Listed exceptions",
        handler=_list,
        card=_list_card,
        summarize_input=lambda a: (
            f"q={a.q or '*'} stage={a.stage or '*'} error={a.error_code or '*'}"
        ),
        summarize_output=lambda o: f"{o.total} exception(s)",
    ),
    ToolSpec(
        name="exceptions.get",
        group=ToolGroup.EXCEPTIONS,
        description=(
            "Get one work item: stage, state, last error, what the automatic fixes tried, the "
            "extracted remittance, its lines and recent history."
        ),
        input_model=GetIn,
        output_model=GetOut,
        permission=Permission.ITEMS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read an item",
        handler=_get,
        card=_get_card,
        summarize_input=lambda a: f"WI-{a.item_id}",
        summarize_output=lambda o: f"{o.item.get('wi')} at {o.item.get('stage')}",
    ),
    ToolSpec(
        name="exceptions.requeue",
        group=ToolGroup.EXCEPTIONS,
        description=(
            "Send a work item back down the pipeline. The item must already be dequeued (locked) "
            "by the person asking; if it is not, say so instead of retrying. The person confirms "
            "with a note about what they fixed."
        ),
        input_model=RequeueIn,
        output_model=RequeueOut,
        permission=Permission.ITEMS_WORK,
        mutating=True,
        confirm_required=True,
        audit_label="Requeued an item",
        handler=_requeue,
        preview=_requeue_preview,
        card=_requeue_card,
        summarize_input=lambda a: f"WI-{a.item_id} -> {a.target_stage or 'current stage'}",
        summarize_output=lambda o: f"WI-{o.item_id} requeued at {o.stage}",
    ),
]
