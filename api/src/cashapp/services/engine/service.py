"""The engine control service: status, pause, resume, drain, throttle, dead-letter replay, audit.

Plain arguments only (no Request). Every mutation opens one unit of work, changes state, writes
its ``ENGINE_AUDIT`` row and commits once, so the change and its audit row stand or fall
together. Status is read on request only: a per-process single-flight cache shares one
computation between every caller, and nothing here starts a background task.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import JsonValue

from cashapp.data.models.engine import EngineAudit, EngineDlqReplay
from cashapp.data.models.outbox import OutboxMessage
from cashapp.data.repositories.config import ConfigSettingRepository
from cashapp.data.repositories.engine import (
    DeadLetterRepository,
    EngineAuditRepository,
    EngineDlqReplayRepository,
    InFlightRepository,
)
from cashapp.data.repositories.flow_query import FlowQueryRepository
from cashapp.data.repositories.poller_heartbeat import PollerHeartbeatRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain import config_keys as ck
from cashapp.domain.clock import Clock
from cashapp.domain.config_keys import ConfigKey
from cashapp.domain.engine import (
    APPLY_PER_RECEIPT_BOUNDS,
    PER_STAGE_BOUNDS,
    STATIONS,
    EngineAction,
    Station,
    StationSpec,
    StationState,
    dead_letter_stages,
    parse_station,
    spec_for,
    stages_of_station,
    station_of_stage,
)
from cashapp.domain.paging import Page
from cashapp.domain.principal import Permission, Principal, Role
from cashapp.domain.receipt_arrived import RECEIPT_ARRIVED_TOPIC
from cashapp.domain.stages import TERMINAL_STATES, Stage
from cashapp.pipeline.bus import EventBus
from cashapp.pipeline.events import TopicNamer
from cashapp.pipeline.health import BusHealth
from cashapp.services.autofix.requeue import (
    InvalidTargetStage,
    ItemNotRequeueable,
    RequeueCommand,
    RequeueService,
)
from cashapp.services.config import (
    ConfigWriter,
    RuntimeConfig,
    StoredSetting,
    effective_value,
    to_json,
)
from cashapp.services.config_groups import ConcurrencyConfig
from cashapp.services.engine import text
from cashapp.services.engine.models import (
    AuditSource,
    DeadLetter,
    EngineActionResult,
    EngineAuditEntry,
    EnginePreview,
    EngineStatus,
    PollerStatus,
    ReplayResult,
    ReplaySkip,
    ReplaySkipReason,
    StationStatus,
    ThrottleStatus,
)
from cashapp.services.locking import ItemBusy, LockConflict, LockForbidden, LockService
from cashapp.services.poller_heartbeat import POLLER_NAMES
from cashapp.settings import Settings

logger = logging.getLogger(__name__)

THROUGHPUT_WINDOW_MINUTES = 5
DEAD_LETTER_SCAN_LIMIT = 2000
DEFAULT_STATUS_CACHE_SECONDS = 5
_ROLE_RANK = (Role.ADMIN, Role.OPERATOR, Role.REVERSER, Role.VIEWER)
_MAX_REASON = 1000


# --------------------------------------------------------------------------- errors


class EngineError(Exception):
    """Base class for engine control errors."""


class EngineForbidden(EngineError):  # noqa: N818
    """The principal lacks Permission.ENGINE_CONTROL."""


class EngineReasonRequired(EngineError):  # noqa: N818
    """A control action needs a reason."""


class EngineConflict(EngineError):  # noqa: N818
    def __init__(self, expected_version: int, current_version: int) -> None:
        self.expected_version = expected_version
        self.current_version = current_version
        super().__init__(
            f"Engine settings are at version {current_version}, not {expected_version}"
        )


class ThrottleOutOfBounds(EngineError):  # noqa: N818
    pass


class UnknownStation(EngineError):  # noqa: N818
    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(f"Unknown station {value!r}")


def require_station(value: str) -> Station:
    station = parse_station(value)
    if station is None:
        raise UnknownStation(value)
    return station


# --------------------------------------------------------------------------- helpers


@dataclass(frozen=True, slots=True)
class _EngineKeys:
    """The four settings that make up the engine's state, read together."""

    paused: tuple[Station, ...]
    draining: tuple[Station, ...]
    per_stage: dict[str, int]
    apply_per_receipt: int
    versions: dict[str, int]

    @property
    def version(self) -> int:
        return sum(self.versions.values())

    def concurrency(self) -> ConcurrencyConfig:
        return ConcurrencyConfig(self.per_stage, self.apply_per_receipt)

    def static_state(self, station: Station) -> StationState:
        """The state a station is in by settings alone (DRAINED needs the in-flight count)."""
        if station in self.draining:
            return StationState.DRAINING
        if station in self.paused:
            return StationState.PAUSED
        return StationState.RUNNING


def _ordered(stations: Sequence[Station] | set[Station]) -> tuple[Station, ...]:
    wanted = set(stations)
    return tuple(spec.station for spec in STATIONS if spec.station in wanted)


def _actor_role(principal: Principal) -> str:
    if principal.is_system:
        return "SYSTEM"
    for role in _ROLE_RANK:
        if role in principal.roles:
            return role.value
    return "NONE"


def _clean_reason(reason: str) -> str:
    cleaned = reason.strip()
    if not cleaned:
        raise EngineReasonRequired("A reason is required")
    if len(cleaned) > _MAX_REASON:
        raise EngineReasonRequired(f"Reason must be at most {_MAX_REASON} characters")
    return cleaned


def _require_control(principal: Principal) -> None:
    if not principal.can(Permission.ENGINE_CONTROL):
        raise EngineForbidden(f"Missing permission {Permission.ENGINE_CONTROL.value}")


def _work_stages(spec: StationSpec) -> tuple[Stage, ...]:
    """Stages whose in-flight and throughput belong to the station."""
    stages: list[Stage] = [] if spec.stage is None else [spec.stage]
    stages.extend(ref.stage for ref in spec.also_gates if ref.stage is not None)
    return tuple(stages)


def _state_view(keys: _EngineKeys) -> dict[str, Any]:
    return {
        "paused_stations": [s.value for s in keys.paused],
        "draining_stations": [s.value for s in keys.draining],
        "per_stage": dict(keys.per_stage),
        "apply_per_receipt": keys.apply_per_receipt,
    }


class StatusCache:
    """Single-flight TTL cache: concurrent callers share one computation per TTL."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._lock = asyncio.Lock()
        self._value: EngineStatus | None = None

    def _fresh(self, ttl_s: float) -> EngineStatus | None:
        value = self._value
        if value is None:
            return None
        age = (self._clock.now() - value.generated_at).total_seconds()
        return value if 0 <= age < ttl_s else None

    async def get(
        self, ttl_s: float, compute: Callable[[], Awaitable[EngineStatus]]
    ) -> EngineStatus:
        cached = self._fresh(ttl_s)
        if cached is not None:
            return cached
        async with self._lock:
            cached = self._fresh(ttl_s)
            if cached is not None:
                return cached
            self._value = await compute()
            return self._value

    def put(self, value: EngineStatus) -> None:
        self._value = value


# --------------------------------------------------------------------------- service


class EngineService:
    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        config: RuntimeConfig,
        bus_health: BusHealth,
        settings: Settings,
        clock: Clock,
        lock_service: LockService,
        requeue: RequeueService,
        bus: EventBus | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._config = config
        self._bus_health = bus_health
        self._bus = bus
        self._settings = settings
        self._clock = clock
        self._locks = lock_service
        self._requeue = requeue
        self._namer = TopicNamer.from_settings(settings.streaming)
        self._writer = ConfigWriter(clock)
        self._cache = StatusCache(clock)

    # ----------------------------------------------------------------- settings

    async def _load_keys(self, uow: UnitOfWork, *, lock: bool) -> _EngineKeys:
        repo = uow.repo(ConfigSettingRepository)
        rows: dict[str, Any] = {}
        if lock:
            for key in (
                ck.ENGINE_PAUSED_STATIONS,
                ck.ENGINE_DRAINING_STATIONS,
                ck.CONCURRENCY_PER_STAGE,
                ck.CONCURRENCY_APPLY_PER_RECEIPT,
            ):  # one fixed order, so two writers can never deadlock
                rows[key.name] = await repo.get_for_update(key.name)
        else:
            rows = {row.key: row for row in await repo.all()}

        def read[T](key: ConfigKey[T]) -> tuple[T, int]:
            row = rows.get(key.name)
            stored = (
                StoredSetting(
                    key.name,
                    cast(JsonValue, row.value),
                    row.version,
                    row.updated_at,
                    row.updated_by,
                )
                if row is not None
                else None
            )
            return effective_value(key, stored)

        paused, v1 = read(ck.ENGINE_PAUSED_STATIONS)
        draining, v2 = read(ck.ENGINE_DRAINING_STATIONS)
        per_stage, v3 = read(ck.CONCURRENCY_PER_STAGE)
        apply_per_receipt, v4 = read(ck.CONCURRENCY_APPLY_PER_RECEIPT)
        return _EngineKeys(
            paused=_ordered(paused),
            draining=_ordered(draining),
            per_stage=dict(per_stage),
            apply_per_receipt=apply_per_receipt,
            versions={
                ck.ENGINE_PAUSED_STATIONS.name: v1,
                ck.ENGINE_DRAINING_STATIONS.name: v2,
                ck.CONCURRENCY_PER_STAGE.name: v3,
                ck.CONCURRENCY_APPLY_PER_RECEIPT.name: v4,
            },
        )

    # ----------------------------------------------------------------- status

    def _dlq_topics(self) -> list[str]:
        return [self._namer.for_stage(stage, "dlq") for stage in dead_letter_stages()]

    async def _bus_lags(self) -> tuple[dict[Stage, int], int | None, bool]:
        """Lag per consumed stage, the receipt topic's lag (None = not measured), bus health."""
        lags: dict[Stage, int] = {}
        healthy = True
        try:
            snapshot = await self._bus_health.snapshot()
            lags = {stage: health["lag"] for stage, health in snapshot.items()}
        except Exception as exc:
            logger.warning("bus lag unavailable: error=%s", type(exc).__name__)
            healthy = False
        receipt_lag: int | None = None
        if self._bus is not None:
            try:
                receipt_lag = await self._bus.consumer_lag(self._namer.named(RECEIPT_ARRIVED_TOPIC))
            except Exception as exc:
                logger.warning("receipt lag unavailable: error=%s", type(exc).__name__)
                receipt_lag = -1
        if any(lag < 0 for lag in lags.values()) or (receipt_lag is not None and receipt_lag < 0):
            healthy = False
        return lags, receipt_lag, healthy

    @staticmethod
    def _lag_of(spec: StationSpec, lags: dict[Stage, int], receipt_lag: int | None) -> int | None:
        if spec.station is Station.INTAKE:
            return 0  # poller-driven: there is no bus backlog in front of it
        if spec.station is Station.AWAIT_RECEIPT:
            return receipt_lag if receipt_lag is not None and receipt_lag >= 0 else None
        values = [
            lags.get(ref.stage, -1) if ref.stage is not None else -1 for ref in spec.consumers
        ]
        return None if any(v < 0 for v in values) else sum(values)

    async def _compute_status(self) -> EngineStatus:
        now = self._clock.now()
        async with self._uow_factory() as uow:  # read-only: leaving the block rolls back
            keys = await self._load_keys(uow, lock=False)
            in_progress = await uow.repo(InFlightRepository).in_progress_by_stage(now)
            waiting = await uow.repo(InFlightRepository).awaiting_count()
            leaves = await uow.repo(FlowQueryRepository).leaves_since(
                now - timedelta(minutes=THROUGHPUT_WINDOW_MINUTES)
            )
            dlq_counts = await uow.repo(DeadLetterRepository).counts_by_topic(self._dlq_topics())
            beats = {
                row.name: row.last_cycle_at
                for row in await uow.repo(PollerHeartbeatRepository).all()
            }
        snapshot = await self._config.snapshot()
        lags, receipt_lag, bus_ok = await self._bus_lags()

        concurrency = keys.concurrency()
        left: dict[Stage, int] = {}
        for _, stage, _ in leaves:
            left[stage] = left.get(stage, 0) + 1

        stations: list[StationStatus] = []
        for spec in STATIONS:
            stages = _work_stages(spec)
            in_flight = sum(in_progress.get(stage, 0) for stage in stages)
            limit = max(concurrency.for_stage(spec.stage), 1) if spec.stage is not None else 1
            if spec.station is Station.INTAKE:
                limit = 1
            dlq = sum(
                dlq_counts.get(self._namer.for_stage(stage, "dlq"), 0)
                for stage in stages_of_station(spec.station)
            )
            state = keys.static_state(spec.station)
            if state is StationState.DRAINING and in_flight == 0:
                state = StationState.DRAINED
            moved = sum(left.get(stage, 0) for stage in stages)
            stations.append(
                StationStatus(
                    station=spec.station,
                    state=state,
                    lag=self._lag_of(spec, lags, receipt_lag),
                    throughput_per_min=round(moved / THROUGHPUT_WINDOW_MINUTES, 2),
                    dlq_depth=dlq,
                    in_flight=in_flight,
                    limit=limit,
                    saturated=in_flight >= limit,
                    waiting=waiting if spec.station is Station.AWAIT_RECEIPT else None,
                )
            )

        intervals = {
            POLLER_NAMES[0]: snapshot.intake().poll_interval_seconds,
            POLLER_NAMES[1]: snapshot.receipt_watcher().poll_interval_seconds,
        }
        pollers = tuple(
            PollerStatus(
                name=name,
                interval_seconds=intervals[name],
                last_beat_at=beats.get(name),
                healthy=beats.get(name) is not None
                and (now - cast(Any, beats[name])).total_seconds() <= 2 * intervals[name],
            )
            for name in POLLER_NAMES
        )
        counts = {state: sum(1 for s in stations if s.state is state) for state in StationState}
        return EngineStatus(
            bus_healthy=bus_ok,
            total_lag=sum(max(lag, 0) for lag in lags.values()) + max(receipt_lag or 0, 0),
            dlq_total=sum(dlq_counts.values()),
            pollers=pollers,
            region=self._settings.object_storage.region,
            consumer_group=self._settings.streaming.consumer_group,
            stations=tuple(stations),
            throttle=ThrottleStatus(dict(keys.per_stage), keys.apply_per_receipt),
            config_version=keys.version,
            counts=counts,
            generated_at=now,
        )

    async def status(self) -> EngineStatus:
        """The engine now; at most ``engine.status_cache_seconds`` old, shared by every caller."""
        try:
            ttl = float(await self._config.get(ck.ENGINE_STATUS_CACHE_SECONDS))
        except Exception:
            ttl = float(DEFAULT_STATUS_CACHE_SECONDS)
        return await self._cache.get(ttl, self._compute_status)

    async def _fresh_status(self) -> EngineStatus:
        value = await self._compute_status()
        self._cache.put(value)
        return value

    # ----------------------------------------------------------------- audit

    async def _add_audit(
        self,
        uow: UnitOfWork,
        *,
        principal: Principal,
        action: EngineAction,
        stations: Sequence[Station],
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        reason: str,
        version: int,
        source: AuditSource,
    ) -> EngineAudit:
        return await uow.repo(EngineAuditRepository).add(
            EngineAudit(
                at=self._clock.now(),
                actor_id=principal.subject,
                actor_name=principal.display_name,
                actor_role=_actor_role(principal),
                action=action.value,
                stations=[s.value for s in stations],
                before_state=before,
                after_state=after,
                reason=reason,
                config_version=version,
                source=source,
            )
        )

    @staticmethod
    def _entry(row: EngineAudit) -> EngineAuditEntry:
        return EngineAuditEntry(
            id=row.id,
            at=row.at,
            actor_id=row.actor_id,
            actor_name=row.actor_name,
            actor_role=row.actor_role,
            action=EngineAction(row.action),
            stations=tuple(Station(value) for value in row.stations),
            before=row.before_state,
            after=row.after_state,
            reason=row.reason,
            config_version=row.config_version,
            source=cast(AuditSource, row.source),
        )

    async def audit(self, offset: int = 0, limit: int | None = None) -> Page[EngineAuditEntry]:
        size = limit if limit is not None else await self._config.get(ck.ENGINE_AUDIT_PAGE_SIZE)
        async with self._uow_factory() as uow:
            page = await uow.repo(EngineAuditRepository).page(offset, size)
        return Page(
            items=[self._entry(row) for row in page.items],
            total=page.total,
            offset=page.offset,
            limit=page.limit,
        )

    # ----------------------------------------------------------------- control

    async def _control(
        self,
        *,
        action: EngineAction,
        stations: Sequence[Station],
        reason: str,
        expected_version: int,
        principal: Principal,
        source: AuditSource,
        compute: Callable[[_EngineKeys], dict[str, object]],
    ) -> EngineActionResult:
        """Check, write the changed keys, add the audit row, commit once."""
        _require_control(principal)
        cleaned = _clean_reason(reason)
        async with self._uow_factory() as uow:
            keys = await self._load_keys(uow, lock=True)
            if keys.version != expected_version:
                raise EngineConflict(expected_version, keys.version)
            before = _state_view(keys)
            versions = dict(keys.versions)
            current: dict[str, Any] = {
                ck.ENGINE_PAUSED_STATIONS.name: [s.value for s in keys.paused],
                ck.ENGINE_DRAINING_STATIONS.name: [s.value for s in keys.draining],
                ck.CONCURRENCY_PER_STAGE.name: dict(keys.per_stage),
                ck.CONCURRENCY_APPLY_PER_RECEIPT.name: keys.apply_per_receipt,
            }
            for name, value in compute(keys).items():
                key = ck.CONFIG_KEYS[name]
                if to_json(key, key.validate(value)) == to_json(key, key.validate(current[name])):
                    continue  # nothing to change: no version bump for a no-op
                versions[name] = await self._writer.set(
                    uow,
                    key,
                    value,
                    principal,
                    cleaned,
                    keys.versions[name],
                    permission=Permission.ENGINE_CONTROL,
                )
                current[name] = value
            after_keys = _EngineKeys(
                paused=_ordered([Station(v) for v in current[ck.ENGINE_PAUSED_STATIONS.name]]),
                draining=_ordered([Station(v) for v in current[ck.ENGINE_DRAINING_STATIONS.name]]),
                per_stage=dict(current[ck.CONCURRENCY_PER_STAGE.name]),
                apply_per_receipt=int(current[ck.CONCURRENCY_APPLY_PER_RECEIPT.name]),
                versions=versions,
            )
            row = await self._add_audit(
                uow,
                principal=principal,
                action=action,
                stations=stations,
                before=before,
                after=_state_view(after_keys),
                reason=cleaned,
                version=after_keys.version,
                source=source,
            )
            entry = self._entry(row)
            await uow.commit()
        self._config.invalidate()
        return EngineActionResult(status=await self._fresh_status(), audit=entry)

    async def pause(
        self,
        station: Station,
        reason: str,
        expected_version: int,
        principal: Principal,
        *,
        source: AuditSource = "api",
    ) -> EngineActionResult:
        def compute(keys: _EngineKeys) -> dict[str, object]:
            return {
                ck.ENGINE_PAUSED_STATIONS.name: [
                    s.value for s in _ordered({*keys.paused, station})
                ],
                ck.ENGINE_DRAINING_STATIONS.name: [
                    s.value for s in keys.draining if s is not station
                ],
            }

        return await self._control(
            action=EngineAction.PAUSE,
            stations=[station],
            reason=reason,
            expected_version=expected_version,
            principal=principal,
            source=source,
            compute=compute,
        )

    async def resume(
        self,
        station: Station,
        reason: str,
        expected_version: int,
        principal: Principal,
        *,
        source: AuditSource = "api",
    ) -> EngineActionResult:
        def compute(keys: _EngineKeys) -> dict[str, object]:
            return {
                ck.ENGINE_PAUSED_STATIONS.name: [s.value for s in keys.paused if s is not station],
                ck.ENGINE_DRAINING_STATIONS.name: [
                    s.value for s in keys.draining if s is not station
                ],
            }

        return await self._control(
            action=EngineAction.RESUME,
            stations=[station],
            reason=reason,
            expected_version=expected_version,
            principal=principal,
            source=source,
            compute=compute,
        )

    async def drain(
        self,
        station: Station,
        reason: str,
        expected_version: int,
        principal: Principal,
        *,
        source: AuditSource = "api",
    ) -> EngineActionResult:
        def compute(keys: _EngineKeys) -> dict[str, object]:
            return {
                ck.ENGINE_PAUSED_STATIONS.name: [
                    s.value for s in _ordered({*keys.paused, station})
                ],
                ck.ENGINE_DRAINING_STATIONS.name: [
                    s.value for s in _ordered({*keys.draining, station})
                ],
            }

        return await self._control(
            action=EngineAction.DRAIN,
            stations=[station],
            reason=reason,
            expected_version=expected_version,
            principal=principal,
            source=source,
            compute=compute,
        )

    @staticmethod
    def _check_throttle(per_stage: int, apply_per_receipt: int) -> None:
        lo, hi = PER_STAGE_BOUNDS
        if not lo <= per_stage <= hi:
            raise ThrottleOutOfBounds(f"Items per stage must be between {lo} and {hi}")
        lo, hi = APPLY_PER_RECEIPT_BOUNDS
        if not lo <= apply_per_receipt <= hi:
            raise ThrottleOutOfBounds(f"Applies per receipt must be between {lo} and {hi}")

    async def set_throttle(
        self,
        per_stage: int,
        apply_per_receipt: int,
        reason: str,
        expected_version: int,
        principal: Principal,
        *,
        source: AuditSource = "api",
    ) -> EngineActionResult:
        self._check_throttle(per_stage, apply_per_receipt)
        lo, hi = PER_STAGE_BOUNDS

        def compute(keys: _EngineKeys) -> dict[str, object]:
            # "*" is the one slider; per-stage overrides stay but are clamped into the bounds.
            merged = {name: min(max(value, lo), hi) for name, value in keys.per_stage.items()}
            merged["*"] = per_stage
            return {
                ck.CONCURRENCY_PER_STAGE.name: merged,
                ck.CONCURRENCY_APPLY_PER_RECEIPT.name: apply_per_receipt,
            }

        return await self._control(
            action=EngineAction.THROTTLE,
            stations=[],
            reason=reason,
            expected_version=expected_version,
            principal=principal,
            source=source,
            compute=compute,
        )

    # ----------------------------------------------------------------- dead letters

    @staticmethod
    def _parse_dead(row: OutboxMessage) -> tuple[UUID, Stage, int | None, int] | None:
        payload = row.payload
        try:
            event_id = UUID(str(payload["event_id"]))
            stage = Stage(payload["stage"])
            raw_item = payload.get("work_item_id")
            item_id = int(raw_item) if raw_item is not None else None
            attempt = int(payload.get("attempt", 0))
        except (KeyError, ValueError, TypeError):
            return None
        return event_id, stage, item_id, attempt

    def _topics_for(self, station: Station | None) -> list[str]:
        if station is None:
            return self._dlq_topics()
        return [self._namer.for_stage(stage, "dlq") for stage in stages_of_station(station)]

    async def list_dead_letters(
        self, station: Station | None, offset: int = 0, limit: int = 50
    ) -> Page[DeadLetter]:
        async with self._uow_factory() as uow:
            page = await uow.repo(DeadLetterRepository).unreplayed(
                self._topics_for(station), offset, limit
            )
            parsed = [(row, self._parse_dead(row)) for row in page.items]
            item_ids = sorted({p[2] for _, p in parsed if p is not None and p[2] is not None})
            items = await uow.repo(FlowQueryRepository).items_by_ids(item_ids)
        letters: list[DeadLetter] = []
        for row, parts in parsed:
            if parts is None:
                continue
            event_id, stage, item_id, attempt = parts
            owner = station_of_stage(stage)
            if owner is None:
                continue
            item = items.get(item_id) if item_id is not None else None
            letters.append(
                DeadLetter(
                    event_id=event_id,
                    station=owner,
                    item_id=item_id,
                    error_code=item.last_error_code.value
                    if item is not None and item.last_error_code is not None
                    else None,
                    attempts=attempt,
                    dead_since=row.created_at,
                )
            )
        return Page(items=letters, total=page.total, offset=page.offset, limit=page.limit)

    async def _replay_one(
        self,
        uow: UnitOfWork,
        parts: tuple[UUID, Stage, int | None, int],
        reason: str,
        principal: Principal,
    ) -> ReplaySkipReason | None:
        """Requeue one dead-lettered item in a savepoint; the skip reason, or None when done."""
        _, stage, item_id, _ = parts
        if item_id is None:
            return "not_found"
        try:
            async with uow.session.begin_nested():
                item = await uow.work_items.get_for_update(item_id, skip_locked=False)
                if item is None:
                    return "not_found"
                if item.state in TERMINAL_STATES:
                    return "done"
                if item.stage is not stage:
                    return "moved_on"
                await self._locks.acquire(uow, item_id, principal)
                await self._requeue.requeue(
                    uow,
                    item_id,
                    RequeueCommand(note=reason, target_stage=stage, learn_alias=False),
                    principal,
                )
        except (LockConflict, ItemBusy):
            return "locked"
        except ItemNotRequeueable:
            return "done"
        except InvalidTargetStage:
            return "moved_on"
        except LockForbidden as exc:
            raise EngineForbidden(str(exc)) from exc
        return None

    async def replay_dead_letters(
        self,
        event_ids: Sequence[UUID],
        reason: str,
        principal: Principal,
        *,
        source: AuditSource = "api",
    ) -> ReplayResult:
        """Send chosen dead letters back to their stage.

        Per event: skip it (locked by a person, done, already replayed, moved on, not found) or
        lock, requeue through the same service a person uses, and record it in the ledger. All of
        it, the main-topic events (through the outbox), the ledger rows and the audit row, is one
        transaction.
        """
        _require_control(principal)
        cleaned = _clean_reason(reason)
        wanted = list(dict.fromkeys(event_ids))
        skipped: list[ReplaySkip] = []
        replayed: list[tuple[UUID, OutboxMessage, tuple[UUID, Stage, int | None, int]]] = []
        async with self._uow_factory() as uow:
            done_before = await uow.repo(EngineDlqReplayRepository).replayed_event_ids(
                [str(e) for e in wanted]
            )
            rows = await uow.repo(DeadLetterRepository).recent_unreplayed(
                self._dlq_topics(), DEAD_LETTER_SCAN_LIMIT
            )
            by_event: dict[UUID, tuple[OutboxMessage, tuple[UUID, Stage, int | None, int]]] = {}
            for row in rows:
                parts = self._parse_dead(row)
                if parts is not None:
                    by_event[parts[0]] = (row, parts)
            audit = await self._add_audit(
                uow,
                principal=principal,
                action=EngineAction.REPLAY,
                stations=[],
                before={"selected": [str(e) for e in wanted]},
                after=None,
                reason=cleaned,
                version=(await self._load_keys(uow, lock=False)).version,
                source=source,
            )
            for event_id in wanted:
                if str(event_id) in done_before:
                    skipped.append(ReplaySkip(event_id, "already_replayed"))
                    continue
                found = by_event.get(event_id)
                if found is None:
                    skipped.append(ReplaySkip(event_id, "not_found"))
                    continue
                why = await self._replay_one(uow, found[1], cleaned, principal)
                if why is not None:
                    skipped.append(ReplaySkip(event_id, why))
                    continue
                replayed.append((event_id, found[0], found[1]))
            touched = _ordered(
                {owner for _, _, p in replayed if (owner := station_of_stage(p[1])) is not None}
            )
            await uow.repo(EngineAuditRepository).update(
                audit,
                stations=[s.value for s in touched],
                after_state={
                    "replayed": [str(e) for e, _, _ in replayed],
                    "skipped": [{"event_id": str(s.event_id), "why": s.why} for s in skipped],
                },
            )
            for event_id, row, parts in replayed:
                await uow.repo(EngineDlqReplayRepository).add(
                    EngineDlqReplay(
                        event_id=str(event_id),
                        outbox_id=row.id,
                        work_item_id=parts[2],
                        stage=parts[1].value,
                        replayed_at=self._clock.now(),
                        audit_id=audit.id,
                    )
                )
            audit_id = audit.id
            await uow.commit()
        self._cache.put(await self._compute_status())
        return ReplayResult(replayed=len(replayed), skipped=tuple(skipped), audit_id=audit_id)

    # ----------------------------------------------------------------- preview (chat)

    async def preview(
        self,
        action: EngineAction,
        stations: Sequence[Station],
        *,
        per_stage: int | None = None,
        apply_per_receipt: int | None = None,
        event_ids: Sequence[UUID] = (),
    ) -> EnginePreview:
        """What a chat confirmation shows: before, after, in-flight, and the version to check."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            keys = await self._load_keys(uow, lock=False)
            in_progress = await uow.repo(InFlightRepository).in_progress_by_stage(now)
        in_flight = sum(
            in_progress.get(stage, 0)
            for station in stations
            for stage in _work_stages(spec_for(station))
        )
        names = ", ".join(s.value for s in stations)
        notes: list[tuple[str, str]] = []
        if any(s in (Station.EXTRACT_READER_A, Station.EXTRACT_READER_B) for s in stations):
            notes.append(("Note", text.EXTRACT_SHARED_NOTE))
        if Station.MATCH_RECEIPT in stations:
            notes.append(("Note", text.FAST_PATH_NOTE))
        if action is EngineAction.THROTTLE:
            if per_stage is None or apply_per_receipt is None:
                raise ThrottleOutOfBounds("Both throttle values are required")
            self._check_throttle(per_stage, apply_per_receipt)
            return EnginePreview(
                what="Set engine concurrency",
                before=(
                    f"{keys.per_stage.get('*', 0)} items per stage, "
                    f"{keys.apply_per_receipt} applies per receipt"
                ),
                after=f"{per_stage} items per stage, {apply_per_receipt} applies per receipt",
                in_flight=sum(in_progress.values()),
                expected_version=keys.version,
                details=(("Effect", text.THROTTLE_EFFECT),),
            )
        if action is EngineAction.REPLAY:
            count = len(set(event_ids))
            return EnginePreview(
                what=f"Replay {count} dead letter{'s' if count != 1 else ''}",
                before=f"{count} selected, sitting in the dead-letter list",
                after=f"{count} sent back to their stage (skips are reported)",
                in_flight=0,
                expected_version=keys.version,
                details=(("Effect", text.REPLAY_EFFECT),),
            )
        station = stations[0]
        before_state = keys.static_state(station)
        target = {
            EngineAction.PAUSE: StationState.PAUSED,
            EngineAction.RESUME: StationState.RUNNING,
            EngineAction.DRAIN: StationState.DRAINING,
        }[action]
        effect = {
            EngineAction.PAUSE: text.PAUSE_EFFECT,
            EngineAction.RESUME: text.RESUME_EFFECT,
            EngineAction.DRAIN: text.DRAIN_EFFECT,
        }[action]
        return EnginePreview(
            what=f"{action.value.capitalize()} station {names}",
            before=f"{names} is {before_state.value}",
            after=f"{names} will be {target.value}",
            in_flight=in_flight,
            expected_version=keys.version,
            details=(
                ("In flight", f"{in_flight} item{'s' if in_flight != 1 else ''}"),
                ("Effect", effect),
                ("Propagation", text.PROPAGATION_NOTE),
                *notes,
            ),
        )
