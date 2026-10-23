"""The stage runner: the one place that consumes an event, claims the item, runs a station and
commits the result.

A concrete station subclasses ``StageRunner`` and implements only ``process``. Everything else
(claim, idempotency guard, the transition, history, the next event, failure handling) lives here
once, so every station behaves the same and redelivery is harmless.
"""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Generator, MutableMapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, ClassVar, Self
from uuid import UUID

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.engine import ConsumerRef
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import SYSTEM_PRINCIPAL, Principal
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.observability.context import bind_item_context
from cashapp.observability.logging import get_logger
from cashapp.observability.tracing import span, station_span
from cashapp.pipeline.bus import Delivery, EventBus, close_stream, next_or_stop
from cashapp.pipeline.errors import MalformedEvent, RunnerInfrastructureError, StageError
from cashapp.pipeline.events import StageEvent, TopicNamer, emit, parse_event
from cashapp.pipeline.failures import (
    Escalate,
    FailureDecision,
    FailureHandler,
    ParkAwaitingReceipt,
    Reroute,
    Resolved,
    Retry,
    decision_kind,
)
from cashapp.pipeline.outcomes import Advance, Archive, Finish, Park, StageOutcome
from cashapp.pipeline.roles import Container, RoleSpec, RoleState
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.engine.pause_gate import PauseGate
from cashapp.services.history import HistoryEntry, record_history

logger = get_logger(__name__)

_MAX_INFRA_BACKOFF_SECONDS = 30


class _ItemLogger(logging.LoggerAdapter[logging.Logger]):
    """Keeps the caller's ``extra`` (the stdlib adapter replaces it before Python 3.13)."""

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        kwargs["extra"] = {**(self.extra or {}), **(kwargs.get("extra") or {})}
        return msg, kwargs


@dataclass(frozen=True, slots=True)
class StageContext:
    uow: UnitOfWork
    item: WorkItem  # loaded FOR UPDATE in ``uow``
    principal: Principal
    config: ConfigSnapshot  # one snapshot per event
    clock: Clock
    log: logging.LoggerAdapter[logging.Logger]
    event: StageEvent
    attempt: int  # ``item.attempts`` at claim time


@dataclass(frozen=True, slots=True)
class RunnerDeps:
    uow_factory: UowFactory
    config: RuntimeConfig
    bus: EventBus
    clock: Clock
    failure_handler: FailureHandler
    namer: TopicNamer
    claim_ttl: timedelta = timedelta(minutes=10)
    pause_gate: PauseGate | None = None

    @classmethod
    def from_container(cls, container: Container) -> Self:
        return cls(
            uow_factory=container.uow_factory,
            config=container.config,
            bus=container.bus,
            clock=container.clock,
            failure_handler=container.failure_handler,
            namer=TopicNamer.from_config(container.runtime.streaming(), container.runtime.env),
            pause_gate=PauseGate(container.config),
        )


class HandleStatus(StrEnum):
    PROCESSED = "PROCESSED"
    SKIPPED = "SKIPPED"
    FAILED_HANDLED = "FAILED_HANDLED"
    DEAD_LETTERED = "DEAD_LETTERED"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True, slots=True)
class HandleResult:
    status: HandleStatus
    outcome: StageOutcome | None = None
    decision: FailureDecision | None = None
    skip_reason: str | None = None  # "stage_mismatch" | "not_claimable"


@contextlib.contextmanager
def _infrastructure() -> Generator[None]:
    """Anything the runner's own bookkeeping raises is an infrastructure failure."""
    try:
        yield
    except RunnerInfrastructureError:
        raise
    except Exception as exc:
        raise RunnerInfrastructureError(type(exc).__name__) from exc


class StageRunner(ABC):
    stage: ClassVar[Stage]

    def __init__(self, deps: RunnerDeps) -> None:
        if not hasattr(type(self), "stage"):
            raise TypeError(f"{type(self).__name__} must set the class attribute 'stage'")
        self.deps = deps
        self._log = get_logger(f"cashapp.pipeline.{self.stage.value.lower()}")
        self._resumable: set[UUID] = set()

    @classmethod
    def build(cls, container: Container) -> Self:
        """Stations that need integrations override this and ``container.resolve`` them."""
        return cls(RunnerDeps.from_container(container))

    @abstractmethod
    async def process(self, ctx: StageContext) -> StageOutcome:
        """The station's own step. Raise ``StageError`` for a classified failure."""

    # --- the shared machinery -----------------------------------------------------------

    async def handle(self, delivery: Delivery) -> HandleResult:
        """Consume one delivery. Final: stations never override it."""
        try:
            event = parse_event(delivery.value)
        except MalformedEvent:
            return await self._dead_letter_malformed(delivery)
        if event.stage != self.stage:
            self._log.info(
                "skipped",
                extra={"reason": "stage_mismatch", "event_stage": event.stage.value},
            )
            await delivery.commit()
            return HandleResult(HandleStatus.SKIPPED, skip_reason="stage_mismatch")
        with bind_item_context(event.work_item_id, self.stage, event.attempt, event.trace_id):
            result = await self._handle_event(event)
        await delivery.commit()
        return result

    async def _dead_letter_malformed(self, delivery: Delivery) -> HandleResult:
        # No item exists to attach an outbox row to, so this goes straight through the bus.
        with _infrastructure():
            await self.deps.bus.publish(
                self.deps.namer.for_stage(self.stage, "dlq"),
                delivery.key,
                delivery.value,
                {
                    **delivery.headers,
                    "error": "malformed",
                    "source-topic": delivery.topic,
                    "source-partition": str(delivery.partition),
                    "source-offset": str(delivery.offset),
                },
            )
        self._log.warning(
            "malformed event sent to dlq",
            extra={
                "topic": delivery.topic,
                "partition": delivery.partition,
                "offset": delivery.offset,
            },
        )
        await delivery.commit()
        return HandleResult(HandleStatus.MALFORMED)

    async def _handle_event(self, event: StageEvent) -> HandleResult:
        resumed = event.event_id in self._resumable
        if not resumed and not await self._claim(event):
            self._log.info("skipped", extra={"reason": "not_claimable"})
            return HandleResult(HandleStatus.SKIPPED, skip_reason="not_claimable")
        try:
            result = await self._run_claimed(event)
        except RunnerInfrastructureError:
            # The claim is ours; the retry of this same delivery resumes without claiming again.
            self._resumable.add(event.event_id)
            raise
        self._resumable.discard(event.event_id)
        return result

    async def _claim(self, event: StageEvent) -> bool:
        """Claim the item in its own transaction; False when this event is a no-op."""
        now = self.deps.clock.now()
        with _infrastructure():
            async with self.deps.uow_factory() as uow:
                item = await uow.work_items.claim(event.work_item_id, stage=self.stage, now=now)
                if item is None:
                    return False
                await uow.work_items.update(
                    item,
                    state=ItemState.IN_PROGRESS,
                    claim_expires_at=now + self.deps.claim_ttl,
                )
                await uow.commit()
        return True

    def _context(
        self, uow: UnitOfWork, item: WorkItem, config: ConfigSnapshot, event: StageEvent
    ) -> StageContext:
        return StageContext(
            uow=uow,
            item=item,
            principal=SYSTEM_PRINCIPAL,
            config=config,
            clock=self.deps.clock,
            log=_ItemLogger(self._log, {}),
            event=event,
            attempt=item.attempts,
        )

    async def _run_claimed(self, event: StageEvent) -> HandleResult:
        with _infrastructure():
            config = await self.deps.config.snapshot()
        failure: Exception
        async with self.deps.uow_factory() as uow:
            with _infrastructure():
                item = await uow.work_items.get_for_update(event.work_item_id, skip_locked=False)
            if item is None or item.stage != self.stage or item.state != ItemState.IN_PROGRESS:
                return HandleResult(HandleStatus.SKIPPED, skip_reason="not_claimable")
            ctx = self._context(uow, item, config, event)
            try:
                with span(station_span(self.stage), work_item_id=item.id):
                    outcome = await self.process(ctx)
            except Exception as exc:
                failure = exc
            else:
                with _infrastructure():
                    await self._apply_outcome(uow, item, outcome, event)
                    await uow.commit()
                return HandleResult(HandleStatus.PROCESSED, outcome=outcome)
        # Leaving the block rolled back whatever the station left uncommitted.
        return await self._handle_failure(event, config, failure)

    async def _apply_outcome(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        outcome: StageOutcome,
        event: StageEvent,
        *,
        error_code: ErrorCode | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write the outcome: state change, history row and (for Advance) the next event."""
        clock = self.deps.clock
        now = clock.now()
        from_stage, from_state = item.stage, item.state
        payload: dict[str, Any] = dict(extra or {})
        emit_next: Stage | None = None
        match outcome:
            case Advance(next_stage, note, advance_payload):
                done = next_stage is Stage.DONE
                await uow.work_items.update(
                    item,
                    stage=next_stage,
                    state=ItemState.DONE if done else ItemState.PENDING,
                    attempts=0,
                    last_error_code=None,
                    last_error_detail=None,
                    claim_expires_at=None,
                )
                reasoning: str | None = note or None
                payload.update(advance_payload or {})
                emit_next = None if done else next_stage
            case Park(state=state, note=note):
                await uow.work_items.update(
                    item,
                    state=state,
                    claim_expires_at=None,
                    awaiting_since=item.awaiting_since if item.awaiting_since is not None else now,
                )
                reasoning = note or None
            case Finish(payment_status, note):
                await uow.work_items.update(
                    item,
                    stage=Stage.DONE,
                    state=ItemState.DONE,
                    payment_status=payment_status,
                    claim_expires_at=None,
                )
                reasoning = note or None
                payload["payment_status"] = payment_status.value
            case Archive(reason):
                await uow.work_items.update(item, state=ItemState.ARCHIVED, claim_expires_at=None)
                reasoning = reason
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.STAGE_TRANSITION,
                from_stage=from_stage,
                to_stage=item.stage,
                from_state=from_state,
                to_state=item.state,
                error_code=error_code,
                reasoning=reasoning,
                payload=payload or None,
            ),
            clock=clock,
        )
        if emit_next is not None:
            await emit(
                uow,
                StageEvent.new(item.id, emit_next, clock=clock, trace_id=event.trace_id),
                item.priority,
                clock=clock,
            )

    # --- failures -----------------------------------------------------------------------

    async def _handle_failure(
        self, event: StageEvent, config: ConfigSnapshot, failure: Exception
    ) -> HandleResult:
        with _infrastructure():
            async with self.deps.uow_factory() as uow:
                item = await uow.work_items.get_for_update(event.work_item_id, skip_locked=False)
                if item is None:
                    return HandleResult(HandleStatus.SKIPPED, skip_reason="not_claimable")
                if isinstance(failure, StageError):
                    result = await self._decide(
                        uow, item, event, config, failure, dead_letter=False
                    )
                else:
                    result = await self._unexpected(uow, item, event, config, failure)
                await uow.commit()
                return result

    async def _unexpected(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        event: StageEvent,
        config: ConfigSnapshot,
        failure: Exception,
    ) -> HandleResult:
        # Type only: the message may carry remittance content.
        self._log.error("station raised", extra={"exception_type": type(failure).__name__})
        detail = {"exception": type(failure).__name__}
        error = StageError(ErrorCode.SYSTEM_DEAD_LETTER, detail)
        retries = config.retries()
        attempts = item.attempts + 1
        if attempts < retries.max_attempts_for(ErrorCode.SYSTEM_DEAD_LETTER):
            decision = Retry(after=timedelta(seconds=retries.backoff_for(attempts)))
            await self._apply_decision(uow, item, event, error, decision, dead_letter=False)
            return HandleResult(HandleStatus.FAILED_HANDLED, decision=decision)
        return await self._decide(uow, item, event, config, error, dead_letter=True)

    async def _decide(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        event: StageEvent,
        config: ConfigSnapshot,
        error: StageError,
        *,
        dead_letter: bool,
    ) -> HandleResult:
        """Ask the failure handler and apply its decision."""
        ctx = self._context(uow, item, config, event)
        try:
            decision = await self.deps.failure_handler.handle(uow, item, error, ctx)
        except Exception as exc:
            # A broken handler must never leave the item IN_PROGRESS.
            self._log.error("failure handler raised", extra={"exception_type": type(exc).__name__})
            await uow.rollback()
            reloaded = await uow.work_items.get_for_update(item.id, skip_locked=False)
            if reloaded is None:
                return HandleResult(HandleStatus.SKIPPED, skip_reason="not_claimable")
            error = StageError(
                ErrorCode.SYSTEM_DEAD_LETTER, {"handler_exception": type(exc).__name__}
            )
            decision = Escalate(None)
            item = reloaded
            dead_letter = True
        await self._apply_decision(uow, item, event, error, decision, dead_letter=dead_letter)
        status = HandleStatus.DEAD_LETTERED if dead_letter else HandleStatus.FAILED_HANDLED
        return HandleResult(status, decision=decision)

    async def _apply_decision(
        self,
        uow: UnitOfWork,
        item: WorkItem,
        event: StageEvent,
        error: StageError,
        decision: FailureDecision,
        *,
        dead_letter: bool,
    ) -> None:
        clock = self.deps.clock
        now = clock.now()
        from_stage, from_state = item.stage, item.state
        await uow.work_items.update(
            item,
            attempts=item.attempts + 1,
            last_error_code=error.code,
            last_error_detail=error.detail,
            claim_expires_at=None,
        )
        payload: dict[str, Any] = {"decision": decision_kind(decision), "attempt": item.attempts}
        retry_event: StageEvent | None = None
        reroute_stage: Stage | None = None
        match decision:
            case Resolved(outcome):
                await self._apply_outcome(
                    uow, item, outcome, event, error_code=error.code, extra=payload
                )
            case Retry(after):
                await uow.work_items.update(item, state=ItemState.PENDING)
                payload["after_seconds"] = int(after.total_seconds())
                retry_event = StageEvent.new(
                    item.id,
                    item.stage,
                    clock=clock,
                    attempt=item.attempts,
                    trace_id=event.trace_id,
                    not_before=now + after,
                )
            case ParkAwaitingReceipt():
                await uow.work_items.update(
                    item,
                    state=ItemState.AWAITING_RECEIPT,
                    awaiting_since=item.awaiting_since if item.awaiting_since is not None else now,
                )
            case Escalate(summary):
                await uow.work_items.update(item, state=ItemState.ESCALATED)
                if summary is not None:
                    await uow.work_items.update(item, escalation_summary=summary)
            case Reroute(stage):
                await uow.work_items.update(item, stage=stage, state=ItemState.PENDING)
                reroute_stage = stage
        if not isinstance(decision, Resolved):
            await record_history(
                uow,
                item.id,
                HistoryEntry(
                    action=HistoryAction.STAGE_TRANSITION,
                    from_stage=from_stage,
                    to_stage=item.stage,
                    from_state=from_state,
                    to_state=item.state,
                    error_code=error.code,
                    reasoning=error.message,
                    payload=payload,
                ),
                clock=clock,
            )
        if retry_event is not None:
            await emit(uow, retry_event, item.priority, kind="retry", clock=clock)
        if reroute_stage is not None:
            await emit(
                uow,
                StageEvent.new(
                    item.id,
                    reroute_stage,
                    clock=clock,
                    attempt=item.attempts,
                    trace_id=event.trace_id,
                ),
                item.priority,
                clock=clock,
            )
        if dead_letter:
            await emit(
                uow,
                StageEvent.new(
                    item.id, self.stage, clock=clock, attempt=item.attempts, trace_id=event.trace_id
                ),
                item.priority,
                kind="dlq",
                clock=clock,
            )


def _role_name(stage: Stage) -> str:
    return stage.value.lower().replace("_", "-")


class StageConsumer:
    """Runs one station: subscribes to its main topic and handles deliveries concurrently."""

    def __init__(
        self,
        runner: StageRunner,
        bus: EventBus,
        group: str,
        *,
        name: str | None = None,
    ) -> None:
        self._runner = runner
        self._bus = bus
        self._group = group
        self._state = RoleState(name or _role_name(runner.stage), "starting")

    def state(self) -> RoleState:
        return self._state

    async def _handle_with_retry(self, delivery: Delivery, stop: asyncio.Event) -> None:
        """Retry the same delivery while the infrastructure is down; never skip its offset."""
        backoff = 1
        while True:
            try:
                await self._runner.handle(delivery)
            except Exception as exc:
                self._state.status = "degraded"
                self._state.detail = type(exc).__name__
                logger.warning(
                    "delivery failed; will retry",
                    extra={"stage": self._runner.stage.value, "error_type": type(exc).__name__},
                )
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                if stop.is_set():
                    return  # not committed: redelivered after the restart
                backoff = min(backoff * 2, _MAX_INFRA_BACKOFF_SECONDS)
            else:
                self._state.status = "running"
                self._state.detail = None
                self._state.last_activity_at = self._runner.deps.clock.now()
                return

    async def run(self, stop: asyncio.Event) -> None:
        runner = self._runner
        topic = runner.deps.namer.for_stage(runner.stage)
        stream = self._bus.subscribe([topic], self._group)
        in_flight: set[asyncio.Task[None]] = set()
        self._state.status = "running"
        try:
            while not stop.is_set():
                concurrency = await runner.deps.config.concurrency()
                limit = max(concurrency.for_stage(runner.stage), 1)
                while len(in_flight) >= limit and not stop.is_set():
                    await asyncio.wait(set(in_flight), return_when=asyncio.FIRST_COMPLETED)
                if stop.is_set():
                    break
                gate = runner.deps.pause_gate
                if gate is not None:
                    # A paused station takes no new delivery; its offsets stay uncommitted.
                    await gate.wait_while_paused(ConsumerRef.for_stage(runner.stage), stop)
                    if stop.is_set():
                        break
                delivery = await next_or_stop(stream, stop)
                if delivery is None:
                    break
                task = asyncio.ensure_future(self._handle_with_retry(delivery, stop))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)
        finally:
            self._state.status = "stopping"
            if in_flight:
                await asyncio.gather(*in_flight, return_exceptions=True)
            await close_stream(stream)
            self._state.status = "stopped"


def consumer_role(runner_cls: type[StageRunner], name: str | None = None) -> RoleSpec:
    """The role that runs ``runner_cls`` as a consumer of its stage's topic."""
    role_name = name if name is not None else _role_name(runner_cls.stage)

    def build(container: Container) -> StageConsumer:
        return StageConsumer(
            runner_cls.build(container),
            container.bus,
            container.runtime.streaming().consumer_group,
            name=role_name,
        )

    return RoleSpec(role_name, "consumer", build)
