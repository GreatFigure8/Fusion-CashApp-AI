"""The extract station: two readers read the same artifact, each result is saved on its own.

Reader A (Opus) and reader B (Cohere) run concurrently under the fan-in timeout. Each reading row
is committed in its own short transaction the moment its reader finishes, so a crash after one
reader keeps that reading and no database transaction is held across a model call. The item then
advances to ADJUDICATE if at least one reader gave a usable reading.
"""

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Self

from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.repositories.artifacts import ArtifactPartRepository
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import (
    SCHEMA_VERSION,
    ReaderSlot,
    ReadingStatus,
    RemittanceExtraction,
)
from cashapp.domain.stages import Stage
from cashapp.integrations.llm.base import LlmClient, LlmClients, LlmError, LlmRequest
from cashapp.integrations.llm.content import (
    ArtifactPartRef,
    FittedParts,
    fit_parts,
    load_content_parts,
)
from cashapp.integrations.storage.base import ObjectNotFound, ObjectStore
from cashapp.observability import llm_span, span
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.services.review.effort import effort_for
from cashapp.stations.extract.prompts import PROMPT_VERSION, build_reader_request

_MESSAGE_MAX = 2000
_SLOTS: tuple[ReaderSlot, ...] = (ReaderSlot.A, ReaderSlot.B)


@dataclass(frozen=True, slots=True)
class ReaderOutcome:
    slot: ReaderSlot
    status: ReadingStatus
    reading_id: int
    model_id: str
    attempt: int
    error_code: ErrorCode | None
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class _Plan:
    slot: ReaderSlot
    client: LlmClient
    request: LlmRequest
    attempt: int
    effort: str | None


class ExtractRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.EXTRACT

    def __init__(self, deps: RunnerDeps, *, object_store: ObjectStore, llm: LlmClients) -> None:
        super().__init__(deps)
        self._store = object_store
        self._llm = llm
        self._uow_factory = deps.uow_factory
        self._clock = deps.clock

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(
            RunnerDeps.from_container(container),
            object_store=container.resolve(ObjectStore),
            llm=container.resolve(LlmClients),
        )

    async def process(self, ctx: StageContext) -> StageOutcome:
        item = ctx.item
        hints = item.fix_hints or {}
        rerun = hints.get("rerun_readers")
        slots = tuple(dict.fromkeys(ReaderSlot(s) for s in rerun)) if rerun else _SLOTS
        models = ctx.config.models()
        # A config change applies to the next event: rebind the models for this one.
        clients = self._llm.with_models(models)

        fitted = await self._load_parts(ctx)
        plans: list[_Plan] = []
        for slot in slots:
            is_a = slot is ReaderSlot.A
            role = models.reader_a if is_a else models.reader_b
            # Cohere has no effort setting; reader A's comes from the one shared lookup.
            effort = effort_for(item, role, ctx.config) if is_a else None
            request = build_reader_request(
                fitted.parts, role=role, effort=effort, slot=slot, work_item_id=item.id
            )
            plans.append(
                _Plan(
                    slot=slot,
                    client=clients.reader_a if is_a else clients.reader_b,
                    request=request,
                    attempt=await self._next_attempt(item.id, slot),
                    effort=effort,
                )
            )

        await self._fan_out(ctx, plans, fitted)

        async with self._uow_factory() as uow:
            latest = await uow.repo(ExtractionReadingRepository).latest_for(item.id)
        summary = {
            slot.value: latest[slot].status.value if slot in latest else "MISSING"
            for slot in _SLOTS
        }
        note = "readers: " + " ".join(f"{k}={v}" for k, v in summary.items())
        if not any(r.status is ReadingStatus.OK for r in latest.values()):
            detail: dict[str, object] = {}
            for slot in _SLOTS:
                reading = latest.get(slot)
                code = reading.error_code if reading is not None else None
                detail[slot.value] = {
                    "status": summary[slot.value],
                    "error_code": code.value if code is not None else None,
                }
            raise StageError(ErrorCode.EXTRACTION_FAILED, detail=detail, message=note)
        reading_a = latest.get(ReaderSlot.A)
        return Advance(
            Stage.ADJUDICATE,
            note=note,
            payload={
                "readings": {slot.value: row.id for slot, row in latest.items()},
                "dropped_part_nos": list(fitted.dropped_part_nos),
                "effort_a": reading_a.effort if reading_a else None,
            },
        )

    async def _load_parts(self, ctx: StageContext) -> FittedParts:
        rows = await ctx.uow.repo(ArtifactPartRepository).for_item(ctx.item.id)
        refs = [ArtifactPartRef.from_row(row) for row in rows]
        if not refs:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_artifact_parts"})
        try:
            content = await load_content_parts(refs, self._store)
        except LlmError as exc:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": exc.detail}) from exc
        except ObjectNotFound as exc:
            raise StageError(
                ErrorCode.EXTRACTION_FAILED, {"reason": "artifact_object_missing"}
            ) from exc
        fitted = fit_parts(content, part_nos=[ref.part_no for ref in refs])
        if not fitted.parts:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "content_over_budget"})
        return fitted

    async def _next_attempt(self, item_id: int, slot: ReaderSlot) -> int:
        async with self._uow_factory() as uow:
            return await uow.repo(ExtractionReadingRepository).max_attempt(item_id, slot) + 1

    async def _fan_out(
        self,
        ctx: StageContext,
        plans: list[_Plan],
        fitted: FittedParts,
    ) -> None:
        fanin_timeout = ctx.config.extraction().fanin_timeout_seconds
        results: dict[ReaderSlot, ReaderOutcome] = {}
        tasks = {
            asyncio.create_task(self._run_reader(ctx, plan, fitted, results)): plan
            for plan in plans
        }
        try:
            _, pending = await asyncio.wait(tasks, timeout=fanin_timeout)
        finally:
            # Also reached on cancellation of the whole station: never leave a reader running.
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in pending:
            plan = tasks[task]
            if plan.slot not in results:
                results[plan.slot] = await self._record(
                    ctx.item.id,
                    plan,
                    fitted,
                    status=ReadingStatus.TIMEOUT,
                    error_code=ErrorCode.LLM_TRANSIENT,
                    message="fan-in timeout",
                )

    async def _run_reader(
        self,
        ctx: StageContext,
        plan: _Plan,
        fitted: FittedParts,
        results: dict[ReaderSlot, ReaderOutcome],
    ) -> None:
        status = ReadingStatus.OK
        error_code: ErrorCode | None = None
        message: str | None = None
        output: dict[str, object] | None = None
        usage = None
        role_name = f"reader_{plan.slot.value.lower()}"
        with span(
            llm_span(role_name), work_item_id=ctx.item.id, model=plan.client.model_id
        ) as active:
            try:
                result = await asyncio.wait_for(
                    plan.client.parse(plan.request, RemittanceExtraction),
                    timeout=plan.request.timeout_s,
                )
                usage = result.usage
                if result.refused or result.output is None:
                    status = ReadingStatus.REFUSED
                    error_code = ErrorCode.LLM_REFUSAL
                else:
                    output = result.output.model_dump(mode="json")
            except TimeoutError:
                status = ReadingStatus.TIMEOUT
                error_code = ErrorCode.LLM_TRANSIENT
                message = "reader timed out"
            except LlmError as exc:
                status = ReadingStatus.FAILED
                error_code = exc.error_code
                usage = exc.usage
                message = exc.detail
            except Exception as exc:  # a client bug must still leave a recorded reading
                status = ReadingStatus.FAILED
                error_code = ErrorCode.EXTRACTION_FAILED
                message = f"unexpected {type(exc).__name__}"
            if usage is not None:
                active.set(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    latency_ms=usage.latency_ms,
                )
        outcome = await self._record(
            ctx.item.id,
            plan,
            fitted,
            status=status,
            error_code=error_code,
            message=message,
            output=output,
            tokens=(usage.input_tokens, usage.output_tokens, usage.latency_ms) if usage else None,
        )
        results[plan.slot] = outcome
        ctx.log.info(
            "reader %s finished status=%s attempt=%d", plan.slot.value, status.value, plan.attempt
        )

    async def _record(
        self,
        item_id: int,
        plan: _Plan,
        fitted: FittedParts,
        *,
        status: ReadingStatus,
        error_code: ErrorCode | None,
        message: str | None,
        output: Mapping[str, object] | None = None,
        tokens: tuple[int, int, int] | None = None,
    ) -> ReaderOutcome:
        """Commit one reading row in its own transaction."""
        notes = [message] if message else []
        if fitted.dropped_part_nos:
            notes.append(f"dropped_part_nos={list(fitted.dropped_part_nos)}")
        row = ExtractionReading(
            work_item_id=item_id,
            reader=plan.slot,
            model_id=plan.client.model_id,
            prompt_version=PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            status=status,
            output=dict(output) if output is not None else None,
            error_code=error_code,
            error_message="; ".join(notes)[:_MESSAGE_MAX] or None,
            input_tokens=tokens[0] if tokens else None,
            output_tokens=tokens[1] if tokens else None,
            latency_ms=tokens[2] if tokens else None,
            attempt=plan.attempt,
            effort=plan.effort,
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.repo(ExtractionReadingRepository).add(row)
            await uow.commit()
        return ReaderOutcome(
            slot=plan.slot,
            status=status,
            reading_id=row.id,
            model_id=row.model_id,
            attempt=plan.attempt,
            error_code=error_code,
            input_tokens=tokens[0] if tokens else 0,
            output_tokens=tokens[1] if tokens else 0,
        )


ROLE = consumer_role(ExtractRunner)
build = ROLE.build
