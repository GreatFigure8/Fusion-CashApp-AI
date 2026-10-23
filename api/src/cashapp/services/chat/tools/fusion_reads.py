"""The assistant's read-only Fusion tools: SQL, REST get, REST describe and the source list.

Registered by discovery (`TOOLS`). None of them writes or needs a confirmation. The audit and the
progress line carry a hash of the SQL, never the SQL text. The SQL guard (one SELECT or WITH)
runs in `FusionExploreService` before any server call.

The tool descriptions are prompt surface: the model reads them to decide what to call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cashapp.services.chat.tools.cards import ResultCard, TableCard, TableColumn
from cashapp.services.chat.tools.registry import ToolContext, ToolError, ToolGroup, ToolSpec
from pydantic import BaseModel, Field

from cashapp.domain.principal import Permission
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.mcp.sql import sql_hash
from cashapp.services.fusion_explore import FusionExploreService

__all__ = ["TOOLS"]


# --- inputs and outputs -----------------------------------------------------------------------


class FusionQueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=20000, description="One SELECT or WITH query.")
    max_rows: int | None = Field(default=None, ge=1, description="Row cap; the setting also caps.")


class FusionQueryOut(BaseModel):
    columns: list[str]
    rows: list[list[str | None]]
    truncated: bool
    total_rows: int | None = None


class FusionRestGetIn(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    params: dict[str, str] | None = None


class FusionRestDescribeIn(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class FusionRestOut(BaseModel):
    status: int
    body: dict[str, Any]
    has_more: bool | None = None


class FusionListSourcesIn(BaseModel):
    pass


class FusionSourceOut(BaseModel):
    name: str
    kind: str
    environment: str | None = None


class FusionSourcesOut(BaseModel):
    sources: list[FusionSourceOut]


# --- helpers ----------------------------------------------------------------------------------


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


async def _explore(ctx: ToolContext) -> FusionExploreService:
    return await ctx.services.get(FusionExploreService)


def _tool_error(exc: FusionError) -> ToolError:
    refused = exc.code.value == "FUSION_FAULT" and not exc.retryable and exc.http_status is None
    return ToolError(
        "INVALID_QUERY" if refused else exc.code.value, exc.message, 422 if refused else 502
    )


# --- handlers ---------------------------------------------------------------------------------


async def _query(ctx: ToolContext, args: FusionQueryIn) -> FusionQueryOut:
    explore = await _explore(ctx)
    try:
        result = await explore.query(args.sql, args.max_rows)
    except FusionError as exc:
        raise _tool_error(exc) from exc
    return FusionQueryOut(
        columns=result.columns,
        rows=[[_text(v) for v in row] for row in result.rows],
        truncated=result.truncated,
        total_rows=result.total_rows,
    )


async def _rest_get(ctx: ToolContext, args: FusionRestGetIn) -> FusionRestOut:
    explore = await _explore(ctx)
    try:
        result = await explore.rest_get(args.path, args.params)
    except FusionError as exc:
        raise _tool_error(exc) from exc
    return FusionRestOut(status=result.status, body=result.body, has_more=result.has_more)


async def _rest_describe(ctx: ToolContext, args: FusionRestDescribeIn) -> FusionRestOut:
    explore = await _explore(ctx)
    try:
        result = await explore.rest_describe(args.path)
    except FusionError as exc:
        raise _tool_error(exc) from exc
    return FusionRestOut(status=result.status, body=result.body, has_more=result.has_more)


async def _list_sources(ctx: ToolContext, _args: FusionListSourcesIn) -> FusionSourcesOut:
    explore = await _explore(ctx)
    try:
        sources = await explore.list_sources()
    except FusionError as exc:
        raise _tool_error(exc) from exc
    return FusionSourcesOut(
        sources=[
            FusionSourceOut(name=s.name, kind=s.kind, environment=s.environment) for s in sources
        ]
    )


# --- summaries and cards ----------------------------------------------------------------------


def _summarize_query_in(args: FusionQueryIn) -> str:
    return f"SQL {sql_hash(args.sql)[:12]} ({len(args.sql)} chars)"


def _summarize_query_out(out: FusionQueryOut) -> str:
    total = out.total_rows if out.total_rows is not None else len(out.rows)
    more = ", more rows exist" if out.truncated else ""
    return f"{len(out.rows)} of {total} rows{more}"


def _query_card(out: FusionQueryOut) -> ResultCard | None:
    if not out.columns:
        return None
    keys = [f"c{i}" for i in range(len(out.columns))]
    return TableCard(
        title="Fusion query",
        columns=[
            TableColumn(key=k, label=label) for k, label in zip(keys, out.columns, strict=True)
        ],
        rows=[dict(zip(keys, row, strict=False)) for row in out.rows],
        total=out.total_rows,
        truncated=out.truncated,
    )


# --- registry entries -------------------------------------------------------------------------

TOOLS: list[ToolSpec[Any, Any]] = [
    ToolSpec(
        name="fusion.query",
        group=ToolGroup.FUSION_READS,
        description=(
            "Run one read-only SQL query (a single SELECT or WITH statement) against the Oracle "
            "Fusion database and return up to the configured row cap. Use it to look at receipts, "
            "invoices, customers and applications when the REST tools cannot answer. Anything "
            "that is not one SELECT or WITH is refused."
        ),
        input_model=FusionQueryIn,
        output_model=FusionQueryOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Queried Fusion with SQL",
        handler=_query,
        card=_query_card,
        summarize_input=_summarize_query_in,
        summarize_output=_summarize_query_out,
        timeout_s=120.0,
    ),
    ToolSpec(
        name="fusion.rest_get",
        group=ToolGroup.FUSION_READS,
        description=(
            "Read one page of an Oracle Fusion REST resource, for example standardReceipts or "
            "receivablesInvoices. `path` is a resource name or a full /fscmRestApi path; `params` "
            "are query parameters (q, fields, limit, offset). Check has_more and pass offset to "
            "read the next page."
        ),
        input_model=FusionRestGetIn,
        output_model=FusionRestOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Read a Fusion REST resource",
        handler=_rest_get,
        summarize_input=lambda a: f"GET {a.path.split('?', 1)[0]}",
    ),
    ToolSpec(
        name="fusion.rest_describe",
        group=ToolGroup.FUSION_READS,
        description=(
            "Describe an Oracle Fusion REST resource: its fields, child resources and actions. "
            "Use it before guessing a field name."
        ),
        input_model=FusionRestDescribeIn,
        output_model=FusionRestOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Described a Fusion REST resource",
        handler=_rest_describe,
        summarize_input=lambda a: f"DESCRIBE {a.path.split('?', 1)[0]}",
    ),
    ToolSpec(
        name="fusion.list_sources",
        group=ToolGroup.FUSION_READS,
        description=(
            "List the Fusion instances and databases the assistant can query, with their "
            "environment (production or non_production)."
        ),
        input_model=FusionListSourcesIn,
        output_model=FusionSourcesOut,
        permission=Permission.REPORTS_READ,
        mutating=False,
        confirm_required=False,
        audit_label="Listed Fusion sources",
        handler=_list_sources,
    ),
]
