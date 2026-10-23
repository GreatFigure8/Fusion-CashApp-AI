"""Chat tools for the Review board: submit staged receipts for in-depth review, list the queue.

Built on the chat-agent-tool-registry contract (``ToolSpec``, ``ToolContext``, ``ConfirmPreview``).
Both tools call the same services the router calls; nothing is re-implemented here.
"""

from typing import Annotated, Any

from cashapp.services.chat.tools.cards import ResultCard, TableCard, TableColumn
from cashapp.services.chat.tools.registry import (
    ConfirmPreview,
    ToolContext,
    ToolError,
    ToolGroup,
    ToolSpec,
    who_line,
)
from pydantic import BaseModel, Field

from cashapp.api.schemas.review import ReviewQueuePage, ReviewQueueRowOut, UploadResultOut
from cashapp.domain.principal import Permission
from cashapp.services.review.queue import ReviewQueueService
from cashapp.services.review.upload import UploadService

_MAX_IDS = 20
_MAX_QUEUE_PAGE = 100


class SubmitIn(BaseModel):
    upload_ids: Annotated[
        list[str],
        Field(
            min_length=1,
            max_length=_MAX_IDS,
            description="Upload ids returned when the files were attached to the chat.",
        ),
    ]


class QueueIn(BaseModel):
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1, le=_MAX_QUEUE_PAGE)] = 20
    open_only: bool = True


async def _service(ctx: ToolContext) -> UploadService:
    return await ctx.services.get(UploadService)


async def _preview_submit(ctx: ToolContext, inp: SubmitIn) -> ConfirmPreview:
    quota = await (await _service(ctx)).quota(ctx.principal)
    count = len(inp.upload_ids)
    return ConfirmPreview(
        what=f"Submit {count} file{'' if count == 1 else 's'} for in-depth review",
        before=f"Today used {quota.used} / {quota.limit}",
        after=f"Today used {quota.used + count} / {quota.limit}",
        who=who_line(ctx.principal),
    )


async def _submit(ctx: ToolContext, inp: SubmitIn) -> UploadResultOut:
    if ctx.confirmation is None:
        raise ToolError("CONFIRMATION_REQUIRED", "This needs your confirmation first.", 409)
    batch = await (await _service(ctx)).submit_staged(inp.upload_ids, ctx.principal)
    return UploadResultOut.from_batch(batch)


def _submit_card(out: UploadResultOut) -> ResultCard | None:
    rows: list[dict[str, str | int | None]] = [
        {
            "file": f.filename,
            "status": f.status.value,
            "item": f"WI-{f.item_id}" if f.item_id is not None else None,
        }
        for f in out.files
    ]
    return TableCard(
        title="Submitted for in-depth review",
        columns=[
            TableColumn(key="file", label="File"),
            TableColumn(key="status", label="Status"),
            TableColumn(key="item", label="Item"),
        ],
        rows=rows,
        total=len(rows),
    )


def _submit_summary(out: UploadResultOut) -> str:
    stored = sum(1 for f in out.files if f.status.value == "STORED")
    return f"{stored} of {len(out.files)} files stored for review"


async def _queue(ctx: ToolContext, inp: QueueIn) -> ReviewQueuePage:
    async with ctx.uow_factory() as uow:
        page = await ReviewQueueService(ctx.clock).page(uow, inp.offset, inp.limit, inp.open_only)
    return ReviewQueuePage(
        items=[ReviewQueueRowOut.from_row(row) for row in page.items],
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )


def _queue_card(out: ReviewQueuePage) -> ResultCard | None:
    rows: list[dict[str, str | int | None]] = [
        {
            "item": f"WI-{row.item_id}",
            "file": row.filename,
            "stage": row.stage.value,
            "status": row.status.value,
        }
        for row in out.items
    ]
    return TableCard(
        title="Review queue",
        columns=[
            TableColumn(key="item", label="Item"),
            TableColumn(key="file", label="File"),
            TableColumn(key="stage", label="Stage"),
            TableColumn(key="status", label="Status"),
        ],
        rows=rows,
        total=out.total,
        truncated=out.total > len(rows),
    )


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="review.submit",
        group=ToolGroup.REVIEW,
        description=(
            "Submit receipt images or PDFs that the person attached to this chat for in-depth "
            "review. Takes the upload ids from the attachment. Each file becomes a work item "
            "that runs the normal stations at high effort."
        ),
        input_model=SubmitIn,
        output_model=UploadResultOut,
        permission=Permission.ITEMS_WORK,
        mutating=True,
        confirm_required=True,
        audit_label="Submit receipts for in-depth review",
        handler=_submit,
        preview=_preview_submit,
        card=_submit_card,
        summarize_input=lambda inp: f"{len(inp.upload_ids)} staged files",
        summarize_output=_submit_summary,
    ),
    ToolSpec(
        name="review.queue",
        group=ToolGroup.REVIEW,
        description=(
            "List items uploaded for in-depth review, newest first, with their stage, status "
            "and filename."
        ),
        input_model=QueueIn,
        output_model=ReviewQueuePage,
        permission=Permission.ITEMS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Listed the review queue",
        handler=_queue,
        card=_queue_card,
    ),
]
