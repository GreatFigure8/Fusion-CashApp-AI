"""The auto-fix suite: does the engine make the decision AR's label says it should?

Each labelled failure is replayed through the matcher to find the error code the new build would
raise (the fixtures carry none), then that code is handed to the real engine through
``FailureHandler.handle``, the same entry point the stage runner calls. The engine runs against a
throwaway in-memory database and makes no model calls: its workhorse client always fails, so the
escalation summary is the deterministic template.
"""

import hashlib
import importlib.util
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UowFactory
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.principal import SYSTEM_PRINCIPAL
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import PRIORITY_LIVE, SourceKind
from cashapp.evals.config import eval_runtime_config
from cashapp.evals.models import (
    AutofixCaseResult,
    AutofixSuiteReport,
    Ratio,
    SuiteStatus,
)
from cashapp.evals.scoring import ConfusionCounter
from cashapp.evals.suites.matching import MessageReplay, replay_message, today_of
from cashapp.integrations.llm.base import LlmClient, LlmClients
from cashapp.integrations.llm.fake import ReplayLlmClient
from cashapp.pipeline.bus import EventBus
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.events import StageEvent
from cashapp.pipeline.failures import FailureDecision, FailureHandler, decision_kind
from cashapp.pipeline.runner import StageContext
from cashapp.services.autofix.engine import build_failure_handler
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import Settings
from cashapp.tools.anonymise.fixture_format import ExpectedDecision, PriorFixtures, expected_for

__all__ = ["not_evaluated", "run_autofix_suite"]

_OTHER: Final = "other"
_LABELS: Final[tuple[str, ...]] = tuple(label.value for label in ExpectedDecision)  # rows
_ACTUALS: Final[tuple[str, ...]] = (*_LABELS, _OTHER)
_MISSING_AIO: Final = (
    "the auto-fix suite needs aiosqlite (a dev dependency): run it with `uv run`, which installs "
    "the dev group"
)


class _EvalClock:
    """A clock the suite can move forward to age an item past its limit."""

    def __init__(self) -> None:
        self._now = datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class _EvalContainer:
    """The few things ``build_failure_handler`` resolves; everything else is refused."""

    def __init__(
        self, *, uow_factory: UowFactory, config: RuntimeConfig, clock: _EvalClock, llm: LlmClients
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config
        self._clock = clock
        self._llm = llm

    @property
    def settings(self) -> Settings:
        raise RuntimeError("settings are not available in the evaluation harness")

    @property
    def runtime(self) -> RuntimeSettings:
        raise RuntimeError("runtime settings are not available in the evaluation harness")

    @property
    def uow_factory(self) -> UowFactory:
        return self._uow_factory

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    @property
    def bus(self) -> EventBus:
        raise RuntimeError("the event bus is not available in the evaluation harness")

    @property
    def clock(self) -> _EvalClock:
        return self._clock

    @property
    def failure_handler(self) -> FailureHandler:
        raise RuntimeError("the failure handler is built by the suite, not resolved")

    def resolve[T](self, key: type[T]) -> T:
        if key is LlmClients:
            return cast(T, self._llm)
        raise KeyError(key)


@asynccontextmanager
async def _memory_uow_factory() -> AsyncGenerator[UowFactory]:
    """An in-memory database with every table, for the engine's history and outbox rows."""
    if importlib.util.find_spec("aiosqlite") is None:
        raise RuntimeError(_MISSING_AIO)
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from cashapp.data.models import Base, load_all_models
    from cashapp.data.uow import make_uow_factory

    load_all_models()
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield make_uow_factory(engine)
    finally:
        await engine.dispose()


def _actual(decisions: list[str]) -> str:
    if decisions == ["matched"]:
        return ExpectedDecision.MATCHED.value
    if decisions == ["park"]:
        return ExpectedDecision.AWAITING_RECEIPT.value
    if decisions == ["park", "escalate"]:
        return ExpectedDecision.ESCALATE_AFTER_AGING.value
    return _OTHER


def _item(message_id: str, stage: Stage) -> WorkItem:
    return WorkItem(
        source_kind=SourceKind.MANUAL,
        content_hash=hashlib.sha256(message_id.encode()).hexdigest(),
        stage=stage,
        state=ItemState.IN_PROGRESS,
        priority=PRIORITY_LIVE,
        info_flags=[],
        attempts=0,
    )


async def _decisions(
    engine: FailureHandler,
    uow_factory: UowFactory,
    config: ConfigSnapshot,
    clock: _EvalClock,
    *,
    message_id: str,
    replay: MessageReplay,
    code: ErrorCode,
    age_out: bool,
) -> list[str]:
    """Hand ``code`` to the engine; for an item that parks, optionally age it out afterwards."""
    log = logging.LoggerAdapter(logging.getLogger("cashapp.evals.autofix"), {})
    async with uow_factory() as uow:
        item = await uow.work_items.add(_item(message_id, replay.stage))

        def context() -> StageContext:
            return StageContext(
                uow=uow,
                item=item,
                principal=SYSTEM_PRINCIPAL,
                config=config,
                clock=clock,
                log=log,
                event=StageEvent.new(item.id, replay.stage, clock=clock),
                attempt=0,
            )

        first: FailureDecision = await engine.handle(uow, item, StageError(code), context())
        decisions = [decision_kind(first)]
        if age_out and decisions == ["park"]:
            clock.advance(timedelta(days=config.aging().awaiting_receipt_max_days + 1))
            aged = await engine.handle(uow, item, StageError(ErrorCode.AGED_OUT), context())
            decisions.append(decision_kind(aged))
        await uow.rollback()
    return decisions


def not_evaluated(reason: str, *, skipped: dict[str, int] | None = None) -> AutofixSuiteReport:
    """An empty report that says nothing was measured."""
    return AutofixSuiteReport(
        status=SuiteStatus.NOT_EVALUATED,
        reason=reason,
        cases=0,
        agreement=Ratio.of(0, 0),
        agreement_by_label={},
        confusion=ConfusionCounter(_LABELS, _ACTUALS).to_model(),
        codes_seen={},
        skipped=skipped or {},
        per_case=[],
    )


def _code_for(replay: MessageReplay) -> ErrorCode | None:
    return None if replay.outcome == "matched" else replay.error_code


async def run_autofix_suite(
    prior: PriorFixtures,
    config: ConfigSnapshot,
    *,
    limit: int | None,
    workhorse: LlmClient | None = None,
) -> AutofixSuiteReport:
    """Decision agreement with the expected decision of each labelled failure."""
    failures = prior.failures if limit is None else prior.failures[:limit]
    if not failures:
        return not_evaluated("no labelled failures found")

    messages = {m.message_id: m for m in prior.messages}
    today = today_of(prior.messages)
    clock = _EvalClock()
    # Every role fails if called: nothing here may reach a model.
    broken = ReplayLlmClient(script={})
    llm = LlmClients(
        reader_a=broken,
        reader_b=broken,
        adjudicator=broken,
        workhorse=workhorse if workhorse is not None else broken,
    )
    matrix = ConfusionCounter(_LABELS, _ACTUALS)
    skipped: dict[str, int] = {}
    codes_seen: dict[str, int] = {}
    by_label: dict[str, list[int]] = {}
    per_case: list[AutofixCaseResult] = []

    async with _memory_uow_factory() as uow_factory:
        container = _EvalContainer(
            uow_factory=uow_factory,
            config=eval_runtime_config(),
            clock=clock,
            llm=llm,
        )
        engine = build_failure_handler(container)
        for failure in failures:
            message = messages.get(failure.message_id)
            if message is None:
                skipped["no_extraction"] = skipped.get("no_extraction", 0) + 1
                continue
            expected = expected_for(failure.label).decision
            replay = await replay_message(message, prior.fusion, config, today=today)
            code = _code_for(replay)
            if code is None:
                decisions = ["matched"]
            else:
                codes_seen[code.value] = codes_seen.get(code.value, 0) + 1
                decisions = await _decisions(
                    engine,
                    uow_factory,
                    config,
                    clock,
                    message_id=failure.message_id,
                    replay=replay,
                    code=code,
                    age_out=expected is ExpectedDecision.ESCALATE_AFTER_AGING,
                )
            actual = _actual(decisions)
            agrees = actual == expected.value
            matrix.add(expected.value, actual)
            counts = by_label.setdefault(failure.label.value, [0, 0])
            counts[0] += int(agrees)
            counts[1] += 1
            per_case.append(
                AutofixCaseResult(
                    message_id=failure.message_id,
                    label=failure.label,
                    error_code=code.value if code else None,
                    decisions=decisions,
                    expected=expected.value,
                    agrees=agrees,
                )
            )

    evaluated = len(per_case)
    if not evaluated:
        return not_evaluated("no labelled failure has a matching prior message", skipped=skipped)
    return AutofixSuiteReport(
        status=SuiteStatus.EVALUATED,
        reason=None,
        cases=evaluated,
        agreement=Ratio.of(sum(1 for c in per_case if c.agrees), evaluated),
        agreement_by_label={
            label: Ratio.of(agree, total) for label, (agree, total) in sorted(by_label.items())
        },
        confusion=matrix.to_model(),
        codes_seen=dict(sorted(codes_seen.items())),
        skipped=skipped,
        per_case=per_case,
    )
