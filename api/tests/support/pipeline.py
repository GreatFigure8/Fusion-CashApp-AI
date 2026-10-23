"""Pipeline test support, registered as a pytest plugin.

``run_stage_once`` drives one delivery through a runner; ``drain_outbox`` reads back what the
runner emitted, without a relay or a bus.
"""

from collections.abc import Iterator
from typing import Any, TypeVar

import pytest

from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock, utcnow
from cashapp.domain.stages import Stage
from cashapp.pipeline.bus import EventBus, InMemoryEventBus, close_stream
from cashapp.pipeline.events import StageEvent, TopicKind, TopicNamer, set_default_namer
from cashapp.pipeline.failures import EscalateAllHandler, FailureDecision, FailureHandler
from cashapp.pipeline.outcomes import StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageRunner
from cashapp.services.config import RuntimeConfig
from cashapp.services.runtime_settings import RuntimeSettings
from cashapp.settings import Settings
from tests.support.clock import FrozenClock
from tests.support.config import make_runtime_config
from tests.support.settings import make_settings, runtime_settings_for

T = TypeVar("T")

TEST_NAMER = TopicNamer("cashapp", "test")


@pytest.fixture(autouse=True)
def _pipeline_namer() -> Iterator[None]:
    set_default_namer(TEST_NAMER)
    try:
        yield
    finally:
        set_default_namer(None)


@pytest.fixture
def memory_bus() -> InMemoryEventBus:
    return InMemoryEventBus(namer=TEST_NAMER)


def make_runner_deps(
    uow_factory: UowFactory,
    *,
    bus: EventBus | None = None,
    config: RuntimeConfig | None = None,
    clock: Clock | None = None,
    failure_handler: FailureHandler | None = None,
) -> RunnerDeps:
    return RunnerDeps(
        uow_factory=uow_factory,
        config=config if config is not None else make_runtime_config(),
        bus=bus if bus is not None else InMemoryEventBus(namer=TEST_NAMER),
        clock=clock if clock is not None else FrozenClock(),
        failure_handler=failure_handler if failure_handler is not None else EscalateAllHandler(),
        namer=TEST_NAMER,
    )


class FakeContainer:
    """Implements ``Container``; ``register`` / ``overrides`` supply ``resolve`` results."""

    def __init__(self, uow_factory: UowFactory, **overrides: Any) -> None:
        self.uow_factory = uow_factory
        self.settings: Settings = overrides.pop("settings", None) or make_settings()
        self.runtime: RuntimeSettings = overrides.pop("runtime", None) or runtime_settings_for()
        self.config: RuntimeConfig = overrides.pop("config", None) or make_runtime_config()
        self.bus: EventBus = overrides.pop("bus", None) or InMemoryEventBus(namer=TEST_NAMER)
        self.clock: Clock = overrides.pop("clock", None) or FrozenClock()
        self.failure_handler: FailureHandler = (
            overrides.pop("failure_handler", None) or EscalateAllHandler()
        )
        if overrides:
            raise TypeError(f"unknown FakeContainer overrides {sorted(overrides)}; use register()")
        self._services: dict[type[Any], Any] = {}

    def register(self, key: type[T], value: T) -> None:
        self._services[key] = value

    def resolve(self, key: type[T]) -> T:
        try:
            return self._services[key]
        except KeyError:
            raise KeyError(f"nothing registered for {key.__name__}") from None


def _as_container(fake: FakeContainer) -> Container:
    """Static check that the fake satisfies the Protocol."""
    return fake


async def run_stage_once(
    runner: StageRunner,
    item_id: int,
    *,
    bus: InMemoryEventBus | None = None,
    event: StageEvent | None = None,
) -> StageOutcome | FailureDecision | None:
    """Publish an event for the item and consume exactly one delivery with ``runner.handle``.

    Returns the outcome, the failure decision, or ``None`` when the event was skipped.
    """
    if bus is None:
        runner_bus = runner.deps.bus
        bus = (
            runner_bus
            if isinstance(runner_bus, InMemoryEventBus)
            else InMemoryEventBus(namer=TEST_NAMER)
        )
    if event is None:
        async with runner.deps.uow_factory() as uow:
            item = await uow.work_items.get(item_id)
            if item is None:
                raise LookupError(f"work item {item_id} does not exist")
            stage = item.stage
        event = StageEvent.new(item_id, stage, clock=runner.deps.clock)
    topic = runner.deps.namer.for_stage(runner.stage)
    await bus.publish(topic, str(item_id), event.model_dump_json().encode("utf-8"))
    stream = bus.subscribe([topic], "run-stage-once")
    try:
        delivery = await anext(stream)
        result = await runner.handle(delivery)
    finally:
        await close_stream(stream)
    return result.outcome if result.outcome is not None else result.decision


async def drain_outbox(uow: UnitOfWork) -> list[StageEvent]:
    """Unpublished outbox rows on stage topics, in id order, parsed and marked published.

    Rows on non-stage topics (for example ``notify``) are left alone. Flushes, never commits.
    """
    namer = TEST_NAMER
    kinds: tuple[TopicKind, ...] = ("main", "retry", "dlq")
    stage_topics = {namer.for_stage(stage, kind) for stage in Stage for kind in kinds}
    page = await uow.outbox.list(
        where=[OutboxMessage.published_at.is_(None)], order_by=[OutboxMessage.id], limit=10_000
    )
    drained = [row for row in page.items if row.topic in stage_topics]
    events = [StageEvent.model_validate(row.payload) for row in drained]
    if drained:
        await uow.outbox.mark_published(drained, at=utcnow())
    return events
