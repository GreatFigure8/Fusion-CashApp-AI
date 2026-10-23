"""Notification sources owned by this story: dead-letter growth and outages.

They run inside the worker host's existing health tick (no new loop) and emit through the outbox.
Summaries are built from stage names, error codes and counts only.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta

from cashapp.data.repositories.notifications import TransientErrorRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.notifications import NotifyEvent, NotifyKind, NotifySeverity
from cashapp.domain.stages import Stage
from cashapp.pipeline.health import BusHealth, StageBusHealth
from cashapp.pipeline.roles import Container
from cashapp.services.notify import emit_notify

OUTAGE_CODES: tuple[ErrorCode, ...] = (ErrorCode.FUSION_TRANSIENT, ErrorCode.LLM_TRANSIENT)


class DlqGrowthSource:
    """Reports a dead-letter queue that grew past the last depth it announced."""

    def __init__(self) -> None:
        self._last_notified: dict[Stage, int] = {}
        self._last_emitted_at: datetime | None = None

    async def check(
        self,
        health: Mapping[Stage, StageBusHealth],
        *,
        now: datetime,
        window_seconds: int,
        clock: Clock,
    ) -> NotifyEvent | None:
        if self._last_emitted_at is not None and now - self._last_emitted_at < timedelta(
            seconds=window_seconds
        ):
            return None  # growth inside the window is reported at the first tick after it
        grown: list[tuple[Stage, int, int]] = []
        for stage, snapshot in health.items():
            depth = snapshot["dlq_depth"]
            if depth < 0:
                continue  # unknown
            previous = self._last_notified.get(stage, 0)
            if depth > previous:
                grown.append((stage, depth - previous, depth))
        if not grown:
            return None
        for stage, _, depth in grown:
            self._last_notified[stage] = depth
        self._last_emitted_at = now
        summary = "; ".join(
            f"{stage.value}: +{delta} (now {depth})" for stage, delta, depth in grown
        )
        return NotifyEvent.new(NotifyKind.DLQ_GROWTH, NotifySeverity.WARNING, summary, clock=clock)


class OutageSource:
    """Reports transient Fusion or LLM errors reaching the configured threshold in the window."""

    def __init__(self) -> None:
        self._last_emitted_at: datetime | None = None

    async def check(
        self,
        uow: UnitOfWork,
        *,
        now: datetime,
        threshold: int,
        window_seconds: int,
        dedupe_seconds: int,
        clock: Clock,
    ) -> NotifyEvent | None:
        if self._last_emitted_at is not None and now - self._last_emitted_at < timedelta(
            seconds=dedupe_seconds
        ):
            return None
        since = now - timedelta(seconds=window_seconds)
        repo = uow.repo(TransientErrorRepository)
        counts = {code: await repo.count_since([code], since) for code in OUTAGE_CODES}
        worst = max(OUTAGE_CODES, key=lambda code: counts[code])
        if counts[worst] < threshold:
            return None
        self._last_emitted_at = now
        minutes = max(1, round(window_seconds / 60))
        return NotifyEvent.new(
            NotifyKind.OUTAGE,
            NotifySeverity.CRITICAL,
            f"{worst.value}: {counts[worst]} in {minutes} min",
            clock=clock,
            error_code=worst,
        )


class NotificationSourcesHook:
    """Health-tick hook (s30 ``HealthTickHook``): runs both sources and emits 0..2 events."""

    def __init__(self) -> None:
        self._dlq = DlqGrowthSource()
        self._outage = OutageSource()

    async def on_tick(self, container: Container, now: datetime) -> None:
        snapshot = await container.config.snapshot()
        window = snapshot.notifications().batch_window_seconds
        try:
            health = await container.resolve(BusHealth).snapshot()
        except KeyError:
            health = {}
        clock = container.clock
        events: list[NotifyEvent] = []
        dlq_event = await self._dlq.check(health, now=now, window_seconds=window, clock=clock)
        if dlq_event is not None:
            events.append(dlq_event)
        async with container.uow_factory() as uow:
            outage_event = await self._outage.check(
                uow,
                now=now,
                threshold=snapshot.get(ck.NOTIFICATIONS_OUTAGE_THRESHOLD),
                window_seconds=snapshot.get(ck.NOTIFICATIONS_OUTAGE_WINDOW_SECONDS),
                dedupe_seconds=window,
                clock=clock,
            )
            if outage_event is not None:
                events.append(outage_event)
            for event in events:
                await emit_notify(uow, event, clock=clock)
            if events:
                await uow.commit()
