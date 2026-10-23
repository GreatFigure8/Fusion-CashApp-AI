"""The one place every MCP tool call is recorded: tool, source, target, rows, duration, outcome and
who asked. Hashes and counts only: SQL text, parameters and bodies never reach the log or the DB."""

from __future__ import annotations

import contextvars
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from cashapp.data.models.mcp_call_log import McpCallLog
from cashapp.data.repositories.mcp_call_log import McpCallLogRepository
from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.mcp_calls import McpCallOutcome
from cashapp.domain.principal import SYSTEM_PRINCIPAL, Principal
from cashapp.integrations.mcp.sql import sql_hash
from cashapp.observability.logging import get_logger

__all__ = [
    "DbMcpCallRecorder",
    "InMemoryMcpCallRecorder",
    "McpCallEntry",
    "McpCallRecorder",
    "acting_as",
    "describe_call",
]

_log = get_logger(__name__)

_actor: contextvars.ContextVar[Principal | None] = contextvars.ContextVar("mcp_actor", default=None)


@contextmanager
def acting_as(principal: Principal) -> Generator[None]:
    """Attribute every MCP call made inside the block to `principal` (default: the system)."""
    token = _actor.set(principal)
    try:
        yield
    finally:
        _actor.reset(token)


def current_actor() -> Principal:
    return _actor.get() or SYSTEM_PRINCIPAL


@dataclass(frozen=True, slots=True)
class McpCallEntry:
    tool: str
    source: str | None
    target_hash: str | None
    target_label: str | None
    rows: int | None
    duration_ms: int
    outcome: McpCallOutcome
    error_code: str | None
    principal_id: str | None
    principal_kind: str  # USER or SYSTEM


class McpCallRecorder(Protocol):
    async def record(self, entry: McpCallEntry) -> None: ...


def _strip_query(path: str) -> str:
    return path.split("?", 1)[0]


def describe_call(
    tool: str, args: Mapping[str, Any], data: Mapping[str, Any] | None
) -> tuple[str | None, str | None, str | None, int | None]:
    """(source, target_label, target_hash, rows) for a call. Never returns SQL text."""
    raw_source = args.get("source")
    source = raw_source if isinstance(raw_source, str) else None
    label: str | None = None
    digest: str | None = None
    if tool == "run_query":
        sql = args.get("sql")
        if isinstance(sql, str):
            digest = sql_hash(sql)
            label = f"sql:{digest[:12]}"
    elif tool.startswith("fusion_rest"):
        path = args.get("path")
        if isinstance(path, str):
            label = _strip_query(path)
            digest = sql_hash(label)
    elif tool == "fetch_rows":
        result_id = args.get("result_id")
        if isinstance(result_id, str):
            digest = sql_hash(result_id)
            label = "fetch_rows"
    return source, label, digest, _row_count(data)


def _row_count(data: Mapping[str, Any] | None) -> int | None:
    if data is None:
        return None
    rows = data.get("rows")
    if isinstance(rows, list):
        return len(rows)  # pyright: ignore[reportUnknownArgumentType]
    body = data.get("body")
    if isinstance(body, Mapping):
        items = body.get("items")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if isinstance(items, list):
            return len(items)  # pyright: ignore[reportUnknownArgumentType]
    return None


def entry_for(
    *,
    tool: str,
    args: Mapping[str, Any],
    data: Mapping[str, Any] | None,
    duration_ms: int,
    outcome: McpCallOutcome,
    error_code: str | None,
) -> McpCallEntry:
    source, label, digest, rows = describe_call(tool, args, data)
    actor = current_actor()
    return McpCallEntry(
        tool=tool,
        source=source,
        target_hash=digest,
        target_label=label,
        rows=rows,
        duration_ms=duration_ms,
        outcome=outcome,
        error_code=error_code,
        principal_id=None if actor.is_system else actor.subject,
        principal_kind="SYSTEM" if actor.is_system else "USER",
    )


class DbMcpCallRecorder:
    """Writes each entry in its own short unit of work. A failure here never fails the call."""

    def __init__(self, uow_factory: UowFactory, *, clock: Clock | None = None) -> None:
        self._uow_factory = uow_factory
        self._clock: Clock = clock if clock is not None else SystemClock()

    async def record(self, entry: McpCallEntry) -> None:
        try:
            async with self._uow_factory() as uow:
                await uow.repo(McpCallLogRepository).add(
                    McpCallLog(
                        created_at=self._clock.now(),
                        tool=entry.tool[:40],
                        source=entry.source[:100] if entry.source else None,
                        target_label=entry.target_label[:200] if entry.target_label else None,
                        target_hash=entry.target_hash,
                        row_count=entry.rows,
                        duration_ms=entry.duration_ms,
                        outcome=entry.outcome.value,
                        error_code=entry.error_code,
                        principal_id=entry.principal_id[:200] if entry.principal_id else None,
                        principal_kind=entry.principal_kind,
                    )
                )
                await uow.commit()
        except Exception as exc:
            _log.warning("mcp call log write failed", extra={"error_type": type(exc).__name__})


class InMemoryMcpCallRecorder:
    """Keeps entries in a list (tests and local runs without a database)."""

    def __init__(self) -> None:
        self.entries: list[McpCallEntry] = []

    async def record(self, entry: McpCallEntry) -> None:
        self.entries.append(entry)
