"""`FakeMcpClient`: a scripted `McpClient` for tests and local runs. No network, no clock."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.mcp.client import REQUIRED_TOOLS, McpHealth
from cashapp.integrations.mcp.errors import error_from_tool_text

__all__ = ["FakeMcpClient", "RecordedCall"]

Handler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class RecordedCall:
    name: str
    args: dict[str, Any]
    write: bool


@dataclass(slots=True)
class _Failure:
    remaining: int
    error: FusionError


@dataclass
class FakeMcpClient:
    tools: list[str] = field(default_factory=lambda: list(REQUIRED_TOOLS))
    calls: list[RecordedCall] = field(default_factory=lambda: list[RecordedCall]())
    closed: bool = False
    _handlers: dict[str, list[Handler]] = field(default_factory=lambda: dict[str, list[Handler]]())
    _failures: list[_Failure] = field(default_factory=lambda: list[_Failure]())

    # --- scripting ---------------------------------------------------------------------------

    def on_tool(self, name: str, handler: Handler) -> None:
        """Handlers for one tool are tried in order; the first to return a result wins."""
        self._handlers.setdefault(name, []).append(handler)

    def rest_pages(self, path_prefix: str, pages: Sequence[Sequence[dict[str, Any]]]) -> None:
        """`fusion_rest_get` for paths starting with `path_prefix` returns `pages` in offset order.

        The page served is picked by `params["offset"]` (the sum of the earlier pages' lengths).
        """
        starts: list[int] = []
        total = 0
        for page in pages:
            starts.append(total)
            total += len(page)

        def handler(args: dict[str, Any]) -> dict[str, Any]:
            path = str(args.get("path", ""))
            if not path.startswith(path_prefix):
                raise _Skip
            params = cast("dict[str, str]", args.get("params") or {})
            offset = int(params.get("offset", "0"))
            index = starts.index(offset) if offset in starts else len(pages)
            items = list(pages[index]) if index < len(pages) else []
            return {
                "status": 200,
                "body": {"items": items, "hasMore": index + 1 < len(pages)},
                "has_more": index + 1 < len(pages),
                "duration_ms": 1,
            }

        self.on_tool("fusion_rest_get", handler)

    def query_result(
        self, marker: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]
    ) -> None:
        """`run_query` whose SQL contains `marker` returns these rows (ready, not truncated)."""

        def handler(args: dict[str, Any]) -> dict[str, Any]:
            if marker not in str(args.get("sql", "")):
                raise _Skip
            return {
                "columns": list(columns),
                "rows": [list(row) for row in rows],
                "truncated": False,
                "total_rows": len(rows),
                "status": "ready",
            }

        self.on_tool("run_query", handler)

    def fail_next(self, times: int, error: FusionError | str) -> None:
        """The next `times` calls fail: with `error`, or with the mapped text of a ToolError."""
        failure = (
            error if isinstance(error, FusionError) else error_from_tool_text(error, write=False)
        )
        self._failures.append(_Failure(times, failure))

    def decimal_body(self, tool: str, body: dict[str, Any]) -> None:
        """Always answer `tool` with `body` (handy for Decimal round-trip checks)."""
        self.on_tool(tool, lambda _args: dict(body))

    # --- McpClient ---------------------------------------------------------------------------

    async def list_tools(self) -> list[str]:
        return list(self.tools)

    async def call_tool(
        self, name: str, args: dict[str, Any], *, write: bool = False
    ) -> dict[str, Any]:
        self.calls.append(RecordedCall(name, dict(args), write))
        for failure in self._failures:
            if failure.remaining > 0:
                failure.remaining -= 1
                raise failure.error
        for handler in self._handlers.get(name, []):
            try:
                result = handler(args)
                if isinstance(result, Awaitable):
                    result = await result
            except _Skip:
                continue
            return result
        raise FusionError(
            ErrorCode.FUSION_FAULT, f"FakeMcpClient has no handler for {name}", retryable=False
        )

    async def health(self) -> McpHealth:
        missing = [t for t in REQUIRED_TOOLS if t not in self.tools]
        if missing:
            return McpHealth(
                False, 1, tuple(self.tools), True, f"missing tools: {', '.join(missing)}"
            )
        return McpHealth(True, 1, tuple(self.tools), True, None)

    async def aclose(self) -> None:
        self.closed = True

    def calls_to(self, name: str) -> list[RecordedCall]:
        return [call for call in self.calls if call.name == name]


class _Skip(Exception):  # noqa: N818 - control flow marker, not an error
    """A handler that does not apply to these arguments."""
