"""Usage recorders: the real one (own short transaction, then the budget check) and the test fake.

The row is written and committed in a UoW of its own, never the station's, so a station that rolls
back still keeps the usage of the calls it made. A recorder never fails the call it observes: every
failure is logged with ids and the exception type only.
"""

import logging
from datetime import UTC, date

from sqlalchemy.exc import IntegrityError

from cashapp.data.engine import create_engine
from cashapp.data.models.llm_usage import LlmUsage
from cashapp.data.repositories.llm_usage import LlmUsageRepository
from cashapp.data.uow import UowFactory, make_uow_factory
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.llm_usage import UsageEntry
from cashapp.services.config import ConfigSnapshot, RuntimeConfig, build_runtime_config
from cashapp.services.llm_usage.budget import check_budget
from cashapp.services.llm_usage.pricing import compute_cost
from cashapp.settings import Settings

__all__ = [
    "DbUsageRecorder",
    "InMemoryUsageRecorder",
    "build_usage_recorder",
    "default_uow_factory",
]

logger = logging.getLogger(__name__)


class DbUsageRecorder:
    """Implements ``UsageRecorder`` over the database."""

    def __init__(
        self, uow_factory: UowFactory, runtime_config: RuntimeConfig, *, clock: Clock | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._config = runtime_config
        self._clock: Clock = clock if clock is not None else SystemClock()
        # The day this process saw the alert fire; it only saves the budget query afterwards.
        self._alerted_day: date | None = None

    async def record(self, entry: UsageEntry) -> None:
        try:
            await self._write(entry)
        except Exception as exc:
            logger.warning(
                "llm_usage_record_failed",
                extra={
                    "work_item_id": entry.work_item_id,
                    "purpose": entry.purpose,
                    "error_type": type(exc).__name__,
                },
            )
            return
        await self._check_budget(entry)

    async def _write(self, entry: UsageEntry) -> None:
        cost = compute_cost(entry.model_id, entry.input_tokens, entry.output_tokens)
        occurred = entry.occurred_at
        async with self._uow_factory() as uow:
            await uow.repo(LlmUsageRepository).add(
                LlmUsage(
                    work_item_id=entry.work_item_id,
                    station=entry.station,
                    purpose=entry.purpose[:100],
                    role=entry.role,
                    provider=entry.provider,
                    model_id=entry.model_id,
                    prompt_version=entry.prompt_version,
                    schema_version=entry.schema_version,
                    effort=entry.effort,
                    input_tokens=entry.input_tokens,
                    output_tokens=entry.output_tokens,
                    latency_ms=entry.latency_ms,
                    cost_usd=cost,
                    outcome=entry.outcome,
                    error_code=entry.error_code,
                    usage_day=occurred.astimezone(UTC).date(),
                    created_at=occurred,
                )
            )
            await uow.commit()

    async def _check_budget(self, entry: UsageEntry) -> None:
        """Alert once per UTC day when spend passes the budget. Never raises."""
        day = entry.occurred_at.astimezone(UTC).date()
        if self._alerted_day == day:
            return
        try:
            limit = (await self._config.budget()).daily_usd
            if limit is None:
                return
            async with self._uow_factory() as uow:
                event = await check_budget(uow, day=day, limit=limit, now=self._clock.now())
                if event is None:
                    return
                await uow.commit()
            self._alerted_day = day
        except IntegrityError:
            # Another worker already alerted for this day.
            self._alerted_day = day
        except Exception as exc:
            logger.warning("llm_budget_check_failed", extra={"error_type": type(exc).__name__})


class InMemoryUsageRecorder:
    """The test fake. ``fail=True`` simulates a database outage (record logs and returns)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.entries: list[UsageEntry] = []
        self.fail = fail

    async def record(self, entry: UsageEntry) -> None:
        if self.fail:
            logger.warning(
                "llm_usage_record_failed",
                extra={"work_item_id": entry.work_item_id, "purpose": entry.purpose},
            )
            return
        self.entries.append(entry)


def build_usage_recorder(
    uow_factory: UowFactory,
    config: RuntimeConfig | ConfigSnapshot | None = None,
    *,
    clock: Clock | None = None,
) -> DbUsageRecorder:
    """A snapshot (or nothing) cannot follow runtime changes, so a fresh RuntimeConfig is built."""
    runtime = config if isinstance(config, RuntimeConfig) else build_runtime_config(uow_factory)
    return DbUsageRecorder(uow_factory, runtime, clock=clock)


_FACTORIES: dict[int, tuple[Settings, UowFactory]] = {}


def default_uow_factory(settings: Settings) -> UowFactory:
    """One small engine per settings object, for callers that pass no UoW factory."""
    cached = _FACTORIES.get(id(settings))
    if cached is not None and cached[0] is settings:
        return cached[1]
    atp = settings.atp
    # create_engine already sets pool_pre_ping; passing it twice would be a TypeError.
    options = {k: v for k, v in atp.engine_kwargs().items() if k != "pool_pre_ping"}
    engine = create_engine(atp.url().render_as_string(hide_password=False), **options)
    factory = make_uow_factory(engine)
    _FACTORIES[id(settings)] = (settings, factory)
    return factory
