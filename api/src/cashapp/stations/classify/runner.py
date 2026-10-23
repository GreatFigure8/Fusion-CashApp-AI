"""The classify station: one cheap Haiku call decides whether the artifact is remittance advice.

A remittance advances to EXTRACT. Anything else is archived with the model's reason (kept, never
dropped) and a person can override from the workbench. The decision row is written in the same
transaction as the stage transition, so a failed attempt leaves no classification behind.
"""

import asyncio
from typing import ClassVar, Self

from cashapp.data.models.classification import Classification
from cashapp.data.repositories.artifacts import ArtifactPartRepository
from cashapp.data.repositories.classification import ClassificationRepository
from cashapp.domain.classification import ClassificationDecision, ClassificationOrigin
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import SYSTEM_PRINCIPAL
from cashapp.domain.stages import Stage
from cashapp.integrations.llm.base import LlmClients, LlmError, LlmErrorCode
from cashapp.integrations.llm.content import ArtifactPartRef, fit_parts, load_content_parts
from cashapp.integrations.storage.base import ObjectNotFound, ObjectStore
from cashapp.observability import Metrics, llm_span, span
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, Archive, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.stations.classify.prompts import PROMPT_VERSION, build_classify_request


class ClassifyRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.CLASSIFY

    def __init__(
        self,
        deps: RunnerDeps,
        *,
        llm: LlmClients,
        object_store: ObjectStore,
        metrics: Metrics | None = None,
    ) -> None:
        super().__init__(deps)
        self._llm = llm
        self._store = object_store
        self._metrics = metrics

    @classmethod
    def build(cls, container: Container) -> Self:
        try:
            metrics: Metrics | None = container.resolve(Metrics)
        except KeyError:
            metrics = None
        return cls(
            RunnerDeps.from_container(container),
            llm=container.resolve(LlmClients),
            object_store=container.resolve(ObjectStore),
            metrics=metrics,
        )

    async def process(self, ctx: StageContext) -> StageOutcome:
        item = ctx.item
        rows = await ctx.uow.repo(ArtifactPartRepository).for_item(item.id)
        if not rows:
            raise StageError(ErrorCode.CLASSIFICATION_FAILED, {"reason": "no_parts"})
        if any(row.purged_at is not None for row in rows):
            raise StageError(ErrorCode.CLASSIFICATION_FAILED, {"reason": "artifact_purged"})
        refs = [ArtifactPartRef.from_row(row) for row in rows]
        # End the read transaction: the item row lock must not be held while the model runs,
        # or a person's lock or override would wait up to the model timeout.
        await ctx.uow.commit()

        try:
            content = await load_content_parts(refs, self._store)
        except LlmError as exc:
            raise StageError(ErrorCode.CLASSIFICATION_FAILED, {"reason": exc.detail}) from exc
        except ObjectNotFound as exc:
            raise StageError(
                ErrorCode.CLASSIFICATION_FAILED, {"reason": "artifact_object_missing"}
            ) from exc
        fitted = fit_parts(content, part_nos=[ref.part_no for ref in refs])
        if not fitted.parts:
            raise StageError(
                ErrorCode.CLASSIFICATION_FAILED,
                {"reason": "nothing_fits", "dropped_part_nos": list(fitted.dropped_part_nos)},
            )

        models = ctx.config.models()  # per event: a config change applies to the next one
        client = self._llm.with_models(models).workhorse
        request = build_classify_request(fitted.parts, role=models.workhorse, work_item_id=item.id)

        with span(llm_span("workhorse"), work_item_id=item.id, model=client.model_id) as active:
            try:
                result = await asyncio.wait_for(
                    client.parse(request, ClassificationDecision),
                    timeout=models.workhorse.timeout_s,
                )
            except TimeoutError as exc:
                raise StageError(
                    ErrorCode.LLM_TRANSIENT,
                    {"provider": client.provider, "model_id": client.model_id, "reason": "timeout"},
                ) from exc
            except LlmError as exc:
                raise self._map_error(exc) from exc
            usage = result.usage
            active.set(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                latency_ms=usage.latency_ms,
            )
        if self._metrics is not None:
            self._metrics.llm_call(
                "workhorse",
                usage.model_id or client.model_id,
                usage.input_tokens,
                usage.output_tokens,
                usage.latency_ms,
            )
        if result.refused:
            raise StageError(
                ErrorCode.LLM_REFUSAL,
                {"stop_reason": result.stop_reason, "model_id": client.model_id},
            )
        decision = result.output
        if decision is None:
            raise StageError(
                ErrorCode.CLASSIFICATION_FAILED,
                {"reason": "no_output", "stop_reason": result.stop_reason},
            )

        row = Classification(
            work_item_id=item.id,
            is_remittance=decision.is_remittance,
            reason=decision.reason,
            confidence=decision.confidence,
            model_id=usage.model_id or client.model_id,
            prompt_version=PROMPT_VERSION,
            origin=ClassificationOrigin.MODEL,
            decided_by=SYSTEM_PRINCIPAL.subject,
            created_at=ctx.clock.now(),
        )
        await ctx.uow.repo(ClassificationRepository).add(row)
        ctx.log.info(
            "classified is_remittance=%s confidence=%.2f model=%s tokens_in=%d tokens_out=%d",
            decision.is_remittance,
            decision.confidence,
            row.model_id,
            usage.input_tokens,
            usage.output_tokens,
        )

        if decision.is_remittance:
            return Advance(
                Stage.EXTRACT,
                note=f"Classified as remittance advice (confidence {decision.confidence:.2f})",
                payload={
                    "classification_id": row.id,
                    "confidence": decision.confidence,
                    "model_id": row.model_id,
                    "prompt_version": PROMPT_VERSION,
                    "dropped_part_nos": list(fitted.dropped_part_nos),
                },
            )
        return Archive(reason=f"Not remittance advice: {decision.reason}")

    @staticmethod
    def _map_error(exc: LlmError) -> StageError:
        detail = {
            "provider": exc.provider,
            "model_id": exc.model_id,
            "reason": exc.detail,
        }
        if exc.code is LlmErrorCode.LLM_TRANSIENT:
            return StageError(ErrorCode.LLM_TRANSIENT, detail)
        if exc.code is LlmErrorCode.LLM_REFUSAL:
            return StageError(ErrorCode.LLM_REFUSAL, detail)
        return StageError(ErrorCode.CLASSIFICATION_FAILED, detail)


ROLE = consumer_role(ClassifyRunner)
build = ROLE.build
