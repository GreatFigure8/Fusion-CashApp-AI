"""The adjudicate station (fan-in): one Opus call compares the two readings and decides.

With two usable readings the adjudicator is called once, on the readings' JSON only. With one
usable reading there is no comparison and no model call: that reading is the result at a reduced
confidence, and the row records which reader was missing. The row is committed before a
low-confidence or ungrounded outcome raises, so a person sees what was proposed.
"""

import asyncio
from decimal import Decimal
from typing import ClassVar, Self

from pydantic import ValidationError

from cashapp.data.models.adjudication import Adjudication
from cashapp.data.models.extraction_reading import ExtractionReading
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.readings import ExtractionReadingRepository
from cashapp.domain.adjudication import (
    ADJUDICATION_SCHEMA_VERSION,
    AdjudicationOrigin,
    AdjudicationResult,
    AdjudicatorDecision,
    check_grounding,
    single_reader_result,
)
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ReaderSlot, ReadingStatus, RemittanceExtraction
from cashapp.domain.stages import Stage
from cashapp.integrations.llm.base import LlmClients, LlmError
from cashapp.integrations.llm.content import fit_parts
from cashapp.observability import llm_span, span
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.stations.adjudicate.prompts import (
    PROMPT_VERSION,
    SINGLE_READER_PROMPT_VERSION,
    build_adjudicator_request,
)

_SLOTS: tuple[ReaderSlot, ...] = (ReaderSlot.A, ReaderSlot.B)


def _usable(
    readings: dict[ReaderSlot, ExtractionReading],
) -> tuple[dict[ReaderSlot, RemittanceExtraction], dict[str, str]]:
    """The valid reading per slot, and per-slot status text for the slots that are not usable."""
    usable: dict[ReaderSlot, RemittanceExtraction] = {}
    status: dict[str, str] = {}
    for slot in _SLOTS:
        row = readings.get(slot)
        if row is None:
            status[slot.value] = "absent"
        elif row.status is not ReadingStatus.OK or row.output is None:
            status[slot.value] = row.status.value
        else:
            try:
                usable[slot] = RemittanceExtraction.model_validate(row.output)
            except ValidationError:
                status[slot.value] = "invalid_output"
    return usable, status


class AdjudicateRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.ADJUDICATE

    def __init__(self, deps: RunnerDeps, *, llm: LlmClients) -> None:
        super().__init__(deps)
        self._llm = llm

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(RunnerDeps.from_container(container), llm=container.resolve(LlmClients))

    async def process(self, ctx: StageContext) -> StageOutcome:
        item = ctx.item
        readings = await ctx.uow.repo(ExtractionReadingRepository).latest_for(item.id)
        usable, status = _usable(readings)
        if not usable:
            raise StageError(ErrorCode.EXTRACTION_FAILED, detail=status)

        missing: ReaderSlot | None
        model_id: str | None
        prompt_version: str
        if len(usable) == 1:
            slot, only = next(iter(usable.items()))
            result = single_reader_result(only, slot)
            missing = ReaderSlot.B if slot is ReaderSlot.A else ReaderSlot.A
            model_id = None
            prompt_version = SINGLE_READER_PROMPT_VERSION
            note = f"single reader {slot.value}"
        else:
            result, model_id = await self._adjudicate(
                ctx, usable[ReaderSlot.A], usable[ReaderSlot.B]
            )
            missing = None
            prompt_version = PROMPT_VERSION
            note = "adjudicated: A+B"

        violations = (
            check_grounding(result, usable[ReaderSlot.A], usable[ReaderSlot.B])
            if missing is None
            else []
        )
        row = await ctx.uow.repo(AdjudicationRepository).add(
            Adjudication(
                work_item_id=item.id,
                origin=AdjudicationOrigin.MODEL,
                model_id=model_id,
                prompt_version=prompt_version,
                schema_version=ADJUDICATION_SCHEMA_VERSION,
                reading_a_id=readings[ReaderSlot.A].id if ReaderSlot.A in readings else None,
                reading_b_id=readings[ReaderSlot.B].id if ReaderSlot.B in readings else None,
                missing_reader=missing,
                final=result.final.model_dump(mode="json"),
                provenance=result.provenance_json(),
                disagreements=[d.model_dump() for d in result.disagreements],
                confidence=Decimal(str(round(result.confidence, 4))),
                created_at=ctx.clock.now(),
            )
        )
        adjudication_id = row.id
        # Commit now so the row survives the StageError below; the transition commit stays the
        # runner's.
        await ctx.uow.commit()

        missing_value = missing.value if missing is not None else None
        if violations:
            raise StageError(
                ErrorCode.UNGROUNDED,
                detail={"adjudication_id": adjudication_id, "paths": violations},
            )
        threshold = ctx.config.escalation().min_extraction_confidence
        if result.confidence < threshold:
            raise StageError(
                ErrorCode.LOW_EXTRACTION_CONFIDENCE,
                detail={
                    "adjudication_id": adjudication_id,
                    "confidence": result.confidence,
                    "threshold": threshold,
                    "missing_reader": missing_value,
                },
            )
        return Advance(
            Stage.VALIDATE,
            note=note,
            payload={
                "adjudication_id": adjudication_id,
                "confidence": result.confidence,
                "missing_reader": missing_value,
                "disagreements": len(result.disagreements),
            },
        )

    async def _adjudicate(
        self, ctx: StageContext, a: RemittanceExtraction, b: RemittanceExtraction
    ) -> tuple[AdjudicationResult, str]:
        models = ctx.config.models()
        client = self._llm.with_models(models).adjudicator
        request = build_adjudicator_request(a, b, role=models.adjudicator, work_item_id=ctx.item.id)
        fitted = fit_parts(request.parts)
        if fitted.dropped_part_nos:
            # A dropped reading must not be passed off as a decision on both.
            raise StageError(
                ErrorCode.EXTRACTION_FAILED, {"reason": "adjudication_input_too_large"}
            )
        with span(
            llm_span("adjudicator"), work_item_id=ctx.item.id, model=client.model_id
        ) as active:
            try:
                llm_result = await asyncio.wait_for(
                    client.parse(request, AdjudicatorDecision), timeout=request.timeout_s
                )
            except TimeoutError as exc:
                raise StageError(
                    ErrorCode.LLM_TRANSIENT, {"reason": "adjudicator_timeout"}
                ) from exc
            except LlmError as exc:
                if exc.usage is not None:
                    active.set(
                        input_tokens=exc.usage.input_tokens,
                        output_tokens=exc.usage.output_tokens,
                        latency_ms=exc.usage.latency_ms,
                    )
                raise StageError(exc.error_code, {"reason": exc.detail}) from exc
            active.set(
                input_tokens=llm_result.usage.input_tokens,
                output_tokens=llm_result.usage.output_tokens,
                latency_ms=llm_result.usage.latency_ms,
            )
        if llm_result.refused or llm_result.output is None:
            raise StageError(ErrorCode.LLM_REFUSAL)
        return AdjudicationResult.from_decision(llm_result.output), client.model_id


ROLE = consumer_role(AdjudicateRunner)
build = ROLE.build
