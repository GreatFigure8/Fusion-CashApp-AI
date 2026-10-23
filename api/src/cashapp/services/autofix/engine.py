"""The auto-fix engine: classify, bound, decide, record, escalate.

``AutoFixEngine`` implements the pipeline's ``FailureHandler``. For every failure a station
raises, it counts the item's earlier attempts at this error code, asks the code's handler for a
decision, and writes one ``AUTOFIX_ATTEMPT`` history row. It sets hints and writes history on the
runner's unit of work and never commits; the runner owns the state change.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import SYSTEM_PRINCIPAL
from cashapp.domain.stages import Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.observability.logging import get_logger
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.failures import (
    Escalate,
    FailureDecision,
    Reroute,
    Retry,
    decision_kind,
)
from cashapp.pipeline.roles import Container
from cashapp.services.actor import actor_fields
from cashapp.services.autofix.attempts import NOOP_LOCKED, AttemptRecord, load_attempts
from cashapp.services.autofix.escalation import announce_escalation
from cashapp.services.autofix.prompts import PROMPT_VERSION
from cashapp.services.autofix.reasoner import (
    LlmReasoner,
    Reasoner,
    TemplateReasoner,
    template_summary,
)
from cashapp.services.config import ConfigSnapshot
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import is_locked_for_automation

if TYPE_CHECKING:
    from cashapp.pipeline.runner import StageContext

logger = get_logger(__name__)


@dataclass(slots=True)
class FixContext:
    uow: UnitOfWork
    item: WorkItem  # loaded FOR UPDATE by the runner
    error: StageError
    attempts_for_code: int  # prior attempts for error.code since the last HUMAN_ACTION
    limit: int  # config.retries().max_attempts_for(error.code)
    config: ConfigSnapshot
    clock: Clock
    reasoner: Reasoner
    stage_ctx: "StageContext"
    _explanation: str | None = field(default=None, repr=False)

    def explain(self, text: str) -> None:
        """The handler's plain-language reasoning, stored on the history row."""
        self._explanation = text

    @property
    def explanation(self) -> str | None:
        return self._explanation


class FixHandler(Protocol):
    async def decide(self, ctx: FixContext) -> FailureDecision: ...


ReasonerFactory = Callable[[ConfigSnapshot], Reasoner]


def _template_factory(_: ConfigSnapshot) -> Reasoner:
    return TemplateReasoner()


class AutoFixEngine:
    """Implements ``FailureHandler``."""

    def __init__(
        self,
        *,
        registry: Mapping[ErrorCode, FixHandler] | None = None,
        reasoner_factory: ReasonerFactory | None = None,
    ) -> None:
        self._registry: dict[ErrorCode, FixHandler] = (
            dict(registry) if registry is not None else default_registry()
        )
        self._reasoner_factory: ReasonerFactory = reasoner_factory or _template_factory

    def register(self, code: ErrorCode, handler: FixHandler) -> None:
        self._registry[code] = handler

    def handler_for(self, code: ErrorCode) -> FixHandler:
        return self._registry[code]

    @property
    def registered_codes(self) -> frozenset[ErrorCode]:
        return frozenset(self._registry)

    async def handle(
        self, uow: UnitOfWork, item: WorkItem, error: StageError, ctx: "StageContext"
    ) -> FailureDecision:
        now = ctx.clock.now()
        if is_locked_for_automation(item, now):
            return await self._noop_locked(uow, item, error, ctx)

        code = error.code
        attempts = await load_attempts(uow, item.id)
        prior = sum(1 for record in attempts if record.error_code == code)
        limit = ctx.config.retries().max_attempts_for(code)
        reasoner = self._reasoner_factory(ctx.config)
        fix_ctx = FixContext(
            uow=uow,
            item=item,
            error=error,
            attempts_for_code=prior,
            limit=limit,
            config=ctx.config,
            clock=ctx.clock,
            reasoner=reasoner,
            stage_ctx=ctx,
        )

        if code.spec.always_person or prior >= limit:
            decision: FailureDecision = Escalate(None)
        else:
            decision = await self.handler_for(code).decide(fix_ctx)
            if isinstance(decision, Retry) and not code.spec.retryable:
                logger.error(
                    "autofix.retry_refused",
                    extra={"error_code": code.value, "work_item_id": item.id},
                )
                decision = Escalate(None)

        prompt_version: str | None = None
        reasoning = fix_ctx.explanation
        if isinstance(decision, Escalate):
            summary = decision.summary
            if summary is None:
                summary = await self._summarise(reasoner, item, error, attempts)
                prompt_version = PROMPT_VERSION
            item.escalation_summary = summary
            await announce_escalation(uow, item, code, summary, clock=ctx.clock)
            decision = Escalate(summary)
            reasoning = summary

        await self._record(
            uow,
            item,
            error,
            decision,
            attempt=prior + 1,
            limit=limit,
            reasoning=reasoning or code.spec.description,
            prompt_version=prompt_version,
            ctx=ctx,
        )
        return decision

    async def _summarise(
        self,
        reasoner: Reasoner,
        item: WorkItem,
        error: StageError,
        attempts: Sequence[AttemptRecord],
    ) -> str:
        """The reasoner's summary, or the template when it raises or returns nothing."""
        try:
            summary = (await reasoner.summarise(item, error, attempts)).strip()
        except Exception as exc:
            logger.warning(
                "autofix.summary_fallback",
                extra={"reason": type(exc).__name__, "work_item_id": item.id},
            )
            summary = ""
        return summary or template_summary(item, error, attempts)

    async def _noop_locked(
        self, uow: UnitOfWork, item: WorkItem, error: StageError, ctx: "StageContext"
    ) -> FailureDecision:
        """A person holds the item: write a marker row and change nothing else."""
        logger.info(
            "autofix.noop_locked",
            extra={"work_item_id": item.id, "error_code": error.code.value},
        )
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.AUTOFIX_ATTEMPT,
                **actor_fields(SYSTEM_PRINCIPAL),
                from_stage=item.stage,
                from_state=item.state,
                error_code=error.code,
                reasoning="The item is locked by a person, so automation did not act on it.",
                payload={"decision": NOOP_LOCKED, "stage": item.stage.value},
            ),
            clock=ctx.clock,
        )
        return Escalate(None)

    async def _record(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        error: StageError,
        decision: FailureDecision,
        *,
        attempt: int,
        limit: int,
        reasoning: str,
        prompt_version: str | None,
        ctx: "StageContext",
    ) -> None:
        reroute_to: Stage | None = decision.stage if isinstance(decision, Reroute) else None
        retry_after = int(decision.after.total_seconds()) if isinstance(decision, Retry) else None
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.AUTOFIX_ATTEMPT,
                **actor_fields(SYSTEM_PRINCIPAL),
                from_stage=item.stage,
                from_state=item.state,
                error_code=error.code,
                reasoning=reasoning,
                payload={
                    "attempt": attempt,
                    "limit": limit,
                    "decision": decision_kind(decision),
                    "stage": item.stage.value,
                    "reroute_to": reroute_to.value if reroute_to is not None else None,
                    "retry_after_seconds": retry_after,
                    "fix_hints": dict(item.fix_hints) if item.fix_hints is not None else None,
                    "prompt_version": prompt_version,
                },
            ),
            clock=ctx.clock,
        )


def default_registry() -> dict[ErrorCode, FixHandler]:
    """A handler for every error code; ``EscalateHandler`` for any code without its own."""
    from cashapp.services.autofix.handlers.escalate import EscalateHandler
    from cashapp.services.autofix.handlers.extraction_failed import RerunFailedReadersHandler
    from cashapp.services.autofix.handlers.fusion_gl_date import GlDateFloorHandler
    from cashapp.services.autofix.handlers.fusion_replan import ReplanLinesHandler
    from cashapp.services.autofix.handlers.low_confidence import LowConfidenceHandler
    from cashapp.services.autofix.handlers.receipt_ambiguous import NarrowReceiptHandler
    from cashapp.services.autofix.handlers.receipt_not_yet_available import (
        ParkAwaitingReceiptHandler,
    )
    from cashapp.services.autofix.handlers.reextract import ReExtractHandler
    from cashapp.services.autofix.handlers.transient import BackoffRetryHandler

    registry: dict[ErrorCode, FixHandler] = {code: EscalateHandler() for code in ErrorCode}
    registry[ErrorCode.RECEIPT_NOT_YET_AVAILABLE] = ParkAwaitingReceiptHandler()
    registry[ErrorCode.RECEIPT_AMBIGUOUS] = NarrowReceiptHandler()
    reextract = ReExtractHandler()
    for code in (
        ErrorCode.CUSTOMER_NOT_FOUND,
        ErrorCode.INVOICE_NOT_FOUND,
        ErrorCode.INVALID_INVOICE_NUMBER,
    ):
        registry[code] = reextract
    registry[ErrorCode.LOW_EXTRACTION_CONFIDENCE] = LowConfidenceHandler()
    rerun = RerunFailedReadersHandler()
    registry[ErrorCode.EXTRACTION_FAILED] = rerun
    registry[ErrorCode.LLM_REFUSAL] = rerun
    replan = ReplanLinesHandler()
    registry[ErrorCode.FUSION_OVERAPPLY] = replan
    registry[ErrorCode.FUSION_ALREADY_APPLIED] = replan
    registry[ErrorCode.FUSION_GL_DATE] = GlDateFloorHandler()
    backoff = BackoffRetryHandler()
    for code in (
        ErrorCode.FUSION_LOCKED,
        ErrorCode.FUSION_TRANSIENT,
        ErrorCode.LLM_TRANSIENT,
    ):
        registry[code] = backoff
    return registry


class _ContainerReasoner:
    """Resolves the LLM clients on the first escalation, so a retry never needs a model."""

    def __init__(self, holder: "_LlmHolder", config: ConfigSnapshot) -> None:
        self._holder = holder
        self._config = config

    async def summarise(
        self, item: WorkItem, error: StageError, attempts: Sequence[AttemptRecord]
    ) -> str:
        reasoner = self._holder.reasoner_for(self._config)
        return await reasoner.summarise(item, error, attempts)


class _LlmHolder:
    def __init__(self, container: Container) -> None:
        self._container = container
        self._clients: object | None = None
        self._missing = False

    def reasoner_for(self, config: ConfigSnapshot) -> Reasoner:
        from cashapp.integrations.llm.base import LlmClients

        if self._missing:
            return TemplateReasoner()
        if self._clients is None:
            try:
                self._clients = self._container.resolve(LlmClients)
            except Exception as exc:  # LookupError when unregistered, config errors otherwise
                self._missing = True
                logger.warning(
                    "autofix.no_llm_clients; escalation summaries use the template",
                    extra={"reason": type(exc).__name__},
                )
                return TemplateReasoner()
        clients = self._clients
        if not isinstance(clients, LlmClients):
            self._missing = True
            return TemplateReasoner()
        return LlmReasoner(clients.workhorse, config.models().workhorse)


def build_failure_handler(container: Container) -> AutoFixEngine:
    """The factory the worker host loads by import path."""
    holder = _LlmHolder(container)

    def factory(config: ConfigSnapshot) -> Reasoner:
        return _ContainerReasoner(holder, config)

    return AutoFixEngine(reasoner_factory=factory)


__all__ = [
    "AutoFixEngine",
    "FixContext",
    "FixHandler",
    "ReasonerFactory",
    "build_failure_handler",
    "default_registry",
]
