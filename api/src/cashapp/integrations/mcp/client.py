"""`McpClient`: the one way the cash app talks to the fusion-sql-mcp (Greenlight) server.

`StreamableHttpMcpClient` holds one long-lived MCP session per process, owned by a background task
(an anyio task group must be entered and left by the same task). It reconnects when a transport
call fails or when the connection settings change, so it is hot and needs no restart. Tool results
are parsed from the text content with `Decimal`, never from the float `structuredContent`.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.mcp_calls import McpCallOutcome
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.jsonutil import loads_decimal
from cashapp.integrations.mcp.errors import McpError, error_from_tool_text, transport_error
from cashapp.integrations.mcp.recorder import McpCallRecorder, entry_for
from cashapp.integrations.mcp.settings import ConfigReader, McpConnection, load_connection
from cashapp.integrations.mcp.token import ClientCredentialsTokenProvider
from cashapp.observability.logging import get_logger
from cashapp.secrets import SecretSource

__all__ = [
    "REQUIRED_TOOLS",
    "McpClient",
    "McpClientOptions",
    "McpHealth",
    "StreamableHttpMcpClient",
]

_log = get_logger(__name__)

# The tools this client calls. `describe_table` is probed by the live test but not required.
REQUIRED_TOOLS: tuple[str, ...] = (
    "list_sources",
    "run_query",
    "fetch_rows",
    "fusion_rest_get",
    "fusion_rest_describe",
    "fusion_rest_write",
)

SleepFn = Callable[[float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class McpHealth:
    ok: bool
    latency_ms: int | None
    tools: tuple[str, ...]
    token_valid: bool
    error: str | None


class McpClient(Protocol):
    async def list_tools(self) -> list[str]: ...

    async def call_tool(
        self, name: str, args: dict[str, Any], *, write: bool = False
    ) -> dict[str, Any]:
        """Call a tool and return its decoded JSON result (a list result is `{"result": [...]}`)."""
        ...

    async def health(self) -> McpHealth: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class McpClientOptions:
    max_attempts: int = 3
    backoff_base_s: float = 0.5
    backoff_max_s: float = 8.0


class _BearerAuth(httpx2.Auth):
    """Adds the bearer token to every MCP request; a 401 refreshes the token and retries once."""

    def __init__(self, tokens: ClientCredentialsTokenProvider, conn: McpConnection) -> None:
        self._tokens = tokens
        self._conn = conn

    async def async_auth_flow(
        self, request: httpx2.Request
    ) -> AsyncGenerator[httpx2.Request, httpx2.Response]:
        request.headers["Authorization"] = f"Bearer {await self._tokens.get_token(self._conn)}"
        response = yield request
        if response.status_code == 401:
            self._tokens.invalidate()
            request.headers["Authorization"] = f"Bearer {await self._tokens.get_token(self._conn)}"
            yield request


class _Session:
    """One connected MCP client, kept open by a task that owns its async contexts."""

    def __init__(self, conn: McpConnection, tokens: ClientCredentialsTokenProvider) -> None:
        self.conn = conn
        self._tokens = tokens
        self._stop = asyncio.Event()
        self._ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._run(), name="mcp-session")
        self.broken = False

    async def _run(self) -> None:
        try:
            auth = _BearerAuth(self._tokens, self.conn)
            async with (
                httpx2.AsyncClient(auth=auth, timeout=float(self.conn.timeout_s)) as http,
                Client(
                    streamable_http_client(self.conn.server_url, http_client=http),
                    read_timeout_seconds=float(self.conn.timeout_s),
                    cache=None,
                ) as client,
            ):
                if not self._ready.done():
                    self._ready.set_result(client)
                await self._stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if not self._ready.done():
                self._ready.set_exception(exc)
            else:
                _log.warning("mcp session ended", extra={"error_type": type(exc).__name__})
        finally:
            self.broken = True
            if not self._ready.done():
                self._ready.set_exception(RuntimeError("mcp session closed"))

    async def client(self) -> Client:
        return await self._ready

    async def close(self) -> None:
        self._stop.set()
        self.broken = True
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=5)
        except (TimeoutError, asyncio.CancelledError, Exception):
            self._task.cancel()
        if self._ready.done() and not self._ready.cancelled():
            self._ready.exception()  # mark retrieved


def _texts(content: Sequence[object]) -> list[str]:
    return [block.text for block in content if isinstance(block, TextContent)]


def _decode(content: Sequence[object]) -> dict[str, Any]:
    """Decode the text content blocks of a tool result into one JSON object."""
    texts = _texts(content)
    if not texts:
        return {}
    try:
        parsed: Any = (
            loads_decimal(texts[0]) if len(texts) == 1 else [loads_decimal(t) for t in texts]
        )
    except ValueError as exc:
        raise McpError(
            ErrorCode.FUSION_FAULT, "the MCP server returned a result that is not JSON"
        ) from exc
    if isinstance(parsed, dict):
        return parsed  # pyright: ignore[reportUnknownVariableType]
    return {"result": parsed}


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


class StreamableHttpMcpClient:
    def __init__(
        self,
        config: ConfigReader,
        secrets: SecretSource,
        recorder: McpCallRecorder,
        *,
        options: McpClientOptions = McpClientOptions(),  # noqa: B008 - frozen value object
        tokens: ClientCredentialsTokenProvider | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self._config = config
        self._recorder = recorder
        self._options = options
        self._sleep = sleep
        self._tokens = tokens if tokens is not None else ClientCredentialsTokenProvider(secrets)
        self._session: _Session | None = None
        self._lock = asyncio.Lock()

    # --- connection --------------------------------------------------------------------------

    async def _ensure(self, conn: McpConnection) -> Client:
        if not conn.configured:
            raise McpError(
                ErrorCode.FUSION_FAULT, "the MCP connection is not configured", retryable=False
            )
        async with self._lock:
            session = self._session
            if session is not None and (session.broken or session.conn.identity != conn.identity):
                self._session = None
                await session.close()
                session = None
            if session is None:
                session = _Session(conn, self._tokens)
                self._session = session
        try:
            return await session.client()
        except McpError:
            await self._drop(session)
            raise
        except Exception as exc:
            await self._drop(session)
            raise self._classify(exc, write=False, sent=False) from None

    async def _drop(self, session: _Session) -> None:
        async with self._lock:
            if self._session is session:
                self._session = None
        await session.close()

    @staticmethod
    def _classify(exc: BaseException, *, write: bool, sent: bool) -> FusionError:
        certainly_not_sent = not sent or isinstance(
            exc, httpx2.ConnectError | httpx2.ConnectTimeout
        )
        return transport_error(
            f"{type(exc).__name__} calling the MCP server",
            write=write,
            certainly_not_sent=certainly_not_sent,
        )

    def _delay(self, attempt: int) -> float:
        cap = min(self._options.backoff_max_s, self._options.backoff_base_s * (2 ** (attempt - 1)))
        return random.uniform(0, cap)  # noqa: S311 - jitter, not security

    # --- calls -------------------------------------------------------------------------------

    async def list_tools(self) -> list[str]:
        conn = await load_connection(self._config)
        client = await self._ensure(conn)
        names: list[str] = []
        cursor: str | None = None
        try:
            while True:
                result = await asyncio.wait_for(
                    client.list_tools(cursor=cursor), timeout=conn.timeout_s
                )
                names.extend(tool.name for tool in result.tools)
                cursor = result.next_cursor
                if not cursor:
                    return names
        except Exception as exc:
            await self._reset()
            raise self._classify(exc, write=False, sent=True) from None

    async def _reset(self) -> None:
        async with self._lock:
            session, self._session = self._session, None
        if session is not None:
            await session.close()

    async def call_tool(
        self, name: str, args: dict[str, Any], *, write: bool = False
    ) -> dict[str, Any]:
        started = time.perf_counter()
        data: dict[str, Any] | None = None
        error: FusionError | None = None
        try:
            data = await self._call_with_retry(name, args, write=write)
            return data
        except FusionError as exc:
            error = exc
            raise
        finally:
            await self._recorder.record(
                entry_for(
                    tool=name,
                    args=args,
                    data=data,
                    duration_ms=_elapsed_ms(started),
                    outcome=McpCallOutcome.OK if error is None else McpCallOutcome.ERROR,
                    error_code=error.code.value if error is not None else None,
                )
            )

    async def _call_with_retry(
        self, name: str, args: dict[str, Any], *, write: bool
    ) -> dict[str, Any]:
        last: FusionError | None = None
        for attempt in range(1, self._options.max_attempts + 1):
            try:
                return await self._call_once(name, args, write=write)
            except FusionError as exc:
                last = exc
                # A write is retried only when nothing was sent; reads retry any transient error.
                retry = exc.retryable and not exc.outcome_unknown
                if not retry or attempt >= self._options.max_attempts:
                    raise
            await self._sleep(self._delay(attempt))
        assert last is not None  # noqa: S101 - the loop always raises or returns
        raise last

    async def _call_once(self, name: str, args: dict[str, Any], *, write: bool) -> dict[str, Any]:
        conn = await load_connection(self._config)
        client = await self._ensure(conn)
        try:
            result = await asyncio.wait_for(client.call_tool(name, args), timeout=conn.timeout_s)
        except FusionError:
            raise
        except Exception as exc:
            await self._reset()
            raise self._classify(exc, write=write, sent=True) from None
        if result.is_error:
            raise error_from_tool_text(" ".join(_texts(result.content)), write=write)
        return _decode(result.content)

    # --- health ------------------------------------------------------------------------------

    async def health(self) -> McpHealth:
        started = time.perf_counter()
        token_valid = False
        try:
            conn = await load_connection(self._config)
            if not conn.configured:
                return McpHealth(False, None, (), False, "not configured")
            await self._tokens.get_token(conn)
            token_valid = True
            tools = await self.list_tools()
        except FusionError as exc:
            return McpHealth(False, None, (), token_valid, exc.message)
        except Exception as exc:
            return McpHealth(False, None, (), token_valid, type(exc).__name__)
        missing = [tool for tool in REQUIRED_TOOLS if tool not in tools]
        if missing:
            return McpHealth(
                False,
                _elapsed_ms(started),
                tuple(tools),
                token_valid,
                f"missing tools: {', '.join(missing)}",
            )
        return McpHealth(True, _elapsed_ms(started), tuple(tools), token_valid, None)

    async def aclose(self) -> None:
        await self._reset()
