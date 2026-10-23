"""The only code that calls a tool handler.

``ToolRunner.execute`` validates the input against the spec's model, checks the permission (a
forbidden call never runs), applies the per-tool timeout, maps expected and unexpected failures,
measures the duration and writes the audit row in its own short unit of work. Tool input and
output text are never logged.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from cashapp.data.uow import UowFactory
from cashapp.domain.clock import Clock
from cashapp.services.chat.audit import ChatToolAudit, ToolAuditEntry
from cashapp.services.chat.tools.registry import (
    ConfirmPreview,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolSpec,
    UnknownTool,
)

logger = logging.getLogger(__name__)

__all__ = ["ToolOutcome", "ToolRunner"]

INPUT_SUMMARY_MAX = 200


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    ok: bool
    outcome: str  # the audit vocabulary: OK | ERROR | FORBIDDEN | INVALID_INPUT | TIMEOUT
    duration_ms: int
    error_code: str | None = None
    message: str | None = None
    output: BaseModel | None = None
    preview: ConfirmPreview | None = None
    parsed_input: BaseModel | None = None
    input_summary: str = ""
    summary: str | None = None
    card: dict[str, Any] | None = None


class ToolRunner:
    def __init__(self, registry: ToolRegistry, uow_factory: UowFactory, clock: Clock) -> None:
        self._registry = registry
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self,
        spec: ToolSpec[Any, Any],
        ctx: ToolContext,
        raw_input: object,
        *,
        phase: str = "run",
        allowed: bool = True,
        preview_only: bool = False,
    ) -> ToolOutcome:
        """Run (or, with ``preview_only``, only preview) one tool call and audit it.

        ``allowed`` is False when the tool was not offered to this caller (group narrowing); the
        call is then refused like a missing permission.
        """
        started = time.perf_counter()
        parsed: BaseModel | None = None
        input_summary = spec.name
        try:
            registered = self._registry.get(spec.name)
        except UnknownTool:
            registered = None
        if registered is not spec:
            outcome = self._failure("ERROR", "UNKNOWN_TOOL", "That tool is not available.")
        elif not allowed or not ctx.principal.can(spec.permission):
            outcome = self._failure(
                "FORBIDDEN", "FORBIDDEN", "You do not have permission to use that tool."
            )
        else:
            try:
                valid: BaseModel = spec.input_model.model_validate(raw_input)
            except ValidationError:
                outcome = self._failure(
                    "INVALID_INPUT",
                    "INVALID_TOOL_INPUT",
                    "The tool input did not match its schema. Check the arguments and retry.",
                )
            else:
                parsed = valid
                input_summary = _summary_of(spec, valid)
                outcome = await self._call(spec, ctx, valid, preview_only)
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = _finish(outcome, duration_ms, parsed, input_summary)
        await self._audit(spec, ctx, result, phase)
        return result

    # --- internals ------------------------------------------------------------------------

    @staticmethod
    def _failure(outcome: str, code: str, message: str) -> "ToolOutcome":
        return ToolOutcome(
            ok=False, outcome=outcome, duration_ms=0, error_code=code, message=message
        )

    async def _call(
        self,
        spec: ToolSpec[Any, Any],
        ctx: ToolContext,
        parsed: BaseModel,
        preview_only: bool,
    ) -> ToolOutcome:
        try:
            async with asyncio.timeout(spec.timeout_s):
                if preview_only:
                    if spec.preview is None:
                        return self._failure("ERROR", "NO_PREVIEW", "That tool has no preview.")
                    preview = await spec.preview(ctx, parsed)
                    return ToolOutcome(ok=True, outcome="OK", duration_ms=0, preview=preview)
                output = await spec.handler(ctx, parsed)
        except TimeoutError:
            return self._failure("TIMEOUT", "TIMEOUT", "The tool took too long and was stopped.")
        except ToolError as exc:
            return self._failure("ERROR", exc.code, exc.message)
        except Exception as exc:
            logger.warning(
                "Chat tool failed",
                extra={"tool": spec.name, "chat_error": type(exc).__name__},
            )
            return self._failure("ERROR", "INTERNAL_ERROR", "The tool hit an unexpected error.")
        card = spec.card(output) if spec.card is not None else None
        return ToolOutcome(
            ok=True,
            outcome="OK",
            duration_ms=0,
            output=output,
            summary=spec.summarize_output(output) if spec.summarize_output is not None else None,
            card=card.model_dump(mode="json") if card is not None else None,
        )

    async def _audit(
        self, spec: ToolSpec[Any, Any], ctx: ToolContext, result: ToolOutcome, phase: str
    ) -> None:
        entry = ToolAuditEntry(
            at=self._clock.now(),
            thread_id=ctx.thread_id,
            call_id=ctx.call_id,
            tool=spec.name,
            audit_label=spec.audit_label,
            actor_subject=ctx.principal.subject,
            actor_name=ctx.principal.display_name,
            input_summary=result.input_summary,
            outcome=result.outcome,
            error_code=result.error_code,
            duration_ms=result.duration_ms,
            phase=phase,
            summary=result.summary,
            result_card=result.card,
        )
        async with self._uow_factory() as uow:
            await ChatToolAudit.record(uow, entry)
            await uow.commit()


def _summary_of(spec: ToolSpec[Any, Any], parsed: BaseModel) -> str:
    if spec.summarize_input is None:
        return spec.name
    return spec.summarize_input(parsed)[:INPUT_SUMMARY_MAX]


def _finish(
    outcome: ToolOutcome, duration_ms: int, parsed: BaseModel | None, input_summary: str
) -> ToolOutcome:
    return ToolOutcome(
        ok=outcome.ok,
        outcome=outcome.outcome,
        duration_ms=duration_ms,
        error_code=outcome.error_code,
        message=outcome.message,
        output=outcome.output,
        preview=outcome.preview,
        parsed_input=parsed,
        input_summary=input_summary,
        summary=outcome.summary,
        card=outcome.card,
    )
