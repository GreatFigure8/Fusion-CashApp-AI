"""The metering decorator: one usage row per model call, for every role.

``MeteredLlmClient`` wraps any ``LlmClient`` and records the call through a ``UsageRecorder`` in
the recorder's own short transaction, never the station's, so a failed station keeps its usage.
The wrapper returns the inner result, or re-raises the inner exception, unchanged. A recorder
failure never fails the call. Entries carry ids, counts and codes only: no prompt, artifact or
output text.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Protocol, Self, runtime_checkable

from pydantic import BaseModel

from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.llm_usage import LlmRole, UsageEntry, UsageOutcome, station_of
from cashapp.integrations.llm.base import (
    LlmClient,
    LlmError,
    LlmErrorCode,
    LlmRequest,
    LlmResult,
    LlmUsage,
)

__all__ = ["MeteredLlmClient", "StreamUsageReporter", "UsageRecorder"]


class UsageRecorder(Protocol):
    async def record(self, entry: UsageEntry) -> None:
        """Persist one entry. Implementations catch and log their own failures; never raises."""
        ...


@runtime_checkable
class StreamUsageReporter(Protocol):
    """A client that can report the final token usage of a streamed reply."""

    def stream_text_metered(
        self, request: LlmRequest, on_usage: Callable[[LlmUsage], None]
    ) -> AsyncIterator[str]: ...


class MeteredLlmClient:
    """Implements ``LlmClient`` by delegating to ``inner`` and recording every call."""

    def __init__(
        self,
        inner: LlmClient,
        role: LlmRole,
        recorder: UsageRecorder,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.inner = inner
        self.role = role
        self._recorder = recorder
        self._clock: Clock = clock if clock is not None else SystemClock()
        # Strong references so a shielded record that outlives a cancelled caller is not collected.
        self._pending: set[asyncio.Future[None]] = set()

    @property
    def provider(self) -> str:
        return self.inner.provider

    @property
    def model_id(self) -> str:
        return self.inner.model_id

    def with_model(self, model_id: str) -> Self:
        return type(self)(
            self.inner.with_model(model_id), self.role, self._recorder, clock=self._clock
        )

    # --- recording ------------------------------------------------------------------------

    def _entry(
        self,
        request: LlmRequest,
        *,
        outcome: UsageOutcome,
        started: float,
        usage: LlmUsage | None = None,
        error_code: str | None = None,
    ) -> UsageEntry:
        latency_ms = usage.latency_ms if usage is not None else 0
        if latency_ms <= 0:
            latency_ms = int((time.perf_counter() - started) * 1000)
        return UsageEntry(
            role=self.role,
            provider=self.inner.provider,
            model_id=usage.model_id if usage is not None else self.inner.model_id,
            purpose=request.purpose,
            station=station_of(request.purpose),
            work_item_id=request.work_item_id,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            effort=request.effort,
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            latency_ms=latency_ms,
            outcome=outcome,
            error_code=error_code,
            occurred_at=self._clock.now(),
        )

    async def _record(self, entry: UsageEntry, *, cancelling: bool = False) -> None:
        """Record under shield so a cancelled caller still leaves its row.

        When ``cancelling`` is true a second cancel while recording is swallowed: the caller
        re-raises the original cancellation, so it is never lost.
        """
        task = asyncio.ensure_future(self._recorder.record(entry))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not cancelling:
                raise

    # --- parse ----------------------------------------------------------------------------

    async def parse[T: BaseModel](self, request: LlmRequest, schema: type[T]) -> LlmResult[T]:
        started = time.perf_counter()
        try:
            result = await self.inner.parse(request, schema)
        except LlmError as exc:
            outcome = (
                UsageOutcome.REFUSED if exc.code == LlmErrorCode.LLM_REFUSAL else UsageOutcome.ERROR
            )
            await self._record(
                self._entry(
                    request,
                    outcome=outcome,
                    started=started,
                    usage=exc.usage,
                    error_code=exc.code.value,
                )
            )
            raise
        except (TimeoutError, asyncio.CancelledError):
            await self._record(
                self._entry(request, outcome=UsageOutcome.TIMEOUT, started=started),
                cancelling=True,
            )
            raise
        except Exception:
            await self._record(self._entry(request, outcome=UsageOutcome.ERROR, started=started))
            raise
        await self._record(
            self._entry(
                request,
                outcome=UsageOutcome.REFUSED if result.refused else UsageOutcome.OK,
                started=started,
                usage=result.usage,
            )
        )
        return result

    # --- stream_text ----------------------------------------------------------------------

    async def stream_text(self, request: LlmRequest) -> AsyncIterator[str]:
        started = time.perf_counter()
        captured: list[LlmUsage] = []
        outcome = UsageOutcome.OK
        error_code: str | None = None
        error_usage: LlmUsage | None = None
        cancelling = False
        try:
            inner = self.inner
            stream: AsyncIterator[str] = (
                inner.stream_text_metered(request, captured.append)
                if isinstance(inner, StreamUsageReporter)
                else inner.stream_text(request)
            )
            async for chunk in stream:
                yield chunk
        except LlmError as exc:
            outcome = (
                UsageOutcome.REFUSED if exc.code == LlmErrorCode.LLM_REFUSAL else UsageOutcome.ERROR
            )
            error_code = exc.code.value
            error_usage = exc.usage
            raise
        except (GeneratorExit, TimeoutError, asyncio.CancelledError):
            # The consumer went away (chat client disconnected) or a deadline fired.
            outcome = UsageOutcome.TIMEOUT
            cancelling = True
            raise
        except Exception:
            outcome = UsageOutcome.ERROR
            raise
        finally:
            usage = captured[-1] if captured else error_usage
            await self._record(
                self._entry(
                    request,
                    outcome=outcome,
                    started=started,
                    usage=usage,
                    error_code=error_code,
                ),
                cancelling=cancelling,
            )
