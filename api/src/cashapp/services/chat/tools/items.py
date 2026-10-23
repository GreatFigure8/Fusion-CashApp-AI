"""Item tools: the history of one work item (what happened, who did it, and why)."""

from typing import Any

from pydantic import BaseModel, Field

from cashapp.domain.principal import Permission
from cashapp.services.chat.tools.cards import TableCard, TableColumn
from cashapp.services.chat.tools.registry import ToolContext, ToolError, ToolGroup, ToolSpec

REASONING_MAX = 300


class HistoryIn(BaseModel):
    item_id: int = Field(description="The work item number, without the WI- prefix.")
    limit: int = Field(default=20, ge=1, le=50, description="How many of the latest entries.")


class HistoryEntryOut(BaseModel):
    at: str
    action: str
    actor: str
    from_stage: str | None
    to_stage: str | None
    error_code: str | None
    reasoning: str | None


class HistoryOut(BaseModel):
    item_id: int
    total: int
    entries: list[HistoryEntryOut]


async def _history(ctx: ToolContext, args: HistoryIn) -> HistoryOut:
    async with ctx.uow_factory() as uow:
        item = await uow.work_items.get(args.item_id)
        if item is None:
            raise ToolError("NOT_FOUND", f"Item {args.item_id} was not found.", 404)
        first = await uow.history.for_item(args.item_id, offset=0, limit=1)
        offset = max(first.total - args.limit, 0)
        page = await uow.history.for_item(args.item_id, offset=offset, limit=args.limit)
    return HistoryOut(
        item_id=args.item_id,
        total=page.total,
        entries=[
            HistoryEntryOut(
                at=row.at.isoformat(),
                action=row.action.value,
                actor=row.actor_name,
                from_stage=row.from_stage.value if row.from_stage else None,
                to_stage=row.to_stage.value if row.to_stage else None,
                error_code=row.error_code.value if row.error_code else None,
                reasoning=row.reasoning[:REASONING_MAX] if row.reasoning else None,
            )
            for row in page.items
        ],
    )


def _card(out: HistoryOut) -> TableCard:
    return TableCard(
        title=f"WI-{out.item_id} history",
        columns=[
            TableColumn(key="at", label="When"),
            TableColumn(key="action", label="Action"),
            TableColumn(key="actor", label="By"),
            TableColumn(key="stage", label="Stage"),
            TableColumn(key="error", label="Error"),
        ],
        rows=[
            {
                "at": e.at,
                "action": e.action,
                "actor": e.actor,
                "stage": e.to_stage,
                "error": e.error_code,
            }
            for e in out.entries
        ],
        total=out.total,
        truncated=out.total > len(out.entries),
    )


TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="items.history",
        group=ToolGroup.EXCEPTIONS,
        description=(
            "Get the latest history entries of one work item: each transition, automatic fix and "
            "human action, with who did it and the reasoning recorded."
        ),
        input_model=HistoryIn,
        output_model=HistoryOut,
        permission=Permission.ITEMS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read item history",
        handler=_history,
        card=_card,
        summarize_input=lambda a: f"WI-{a.item_id} (last {a.limit})",
        summarize_output=lambda o: f"{len(o.entries)} of {o.total} entries",
    ),
]
