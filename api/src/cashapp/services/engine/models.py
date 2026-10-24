"""Plain result types of the engine service. The API layer shapes these into Pydantic schemas."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from cashapp.domain.engine import EngineAction, Station, StationState

ReplaySkipReason = Literal["locked", "done", "already_replayed", "moved_on", "not_found"]
AuditSource = Literal["api", "chat"]


@dataclass(frozen=True, slots=True)
class StationStatus:
    station: Station
    state: StationState
    lag: int | None  # None = unknown
    throughput_per_min: float  # mean of the last five minutes
    dlq_depth: int
    in_flight: int
    limit: int
    saturated: bool
    waiting: int | None  # await_receipt only


@dataclass(frozen=True, slots=True)
class PollerStatus:
    name: str
    interval_seconds: int
    last_beat_at: datetime | None
    healthy: bool


@dataclass(frozen=True, slots=True)
class ThrottleStatus:
    per_stage: Mapping[str, int]
    apply_per_receipt: int


@dataclass(frozen=True, slots=True)
class EngineStatus:
    bus_healthy: bool
    total_lag: int
    dlq_total: int
    pollers: tuple[PollerStatus, ...]
    region: str
    consumer_group: str
    stations: tuple[StationStatus, ...]
    throttle: ThrottleStatus
    config_version: int
    counts: Mapping[StationState, int]
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class EngineAuditEntry:
    id: int
    at: datetime
    actor_id: str
    actor_name: str
    actor_role: str
    action: EngineAction
    stations: tuple[Station, ...]
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    reason: str
    config_version: int
    source: AuditSource


@dataclass(frozen=True, slots=True)
class EngineActionResult:
    status: EngineStatus
    audit: EngineAuditEntry


@dataclass(frozen=True, slots=True)
class DeadLetter:
    event_id: UUID
    station: Station
    item_id: int | None
    error_code: str | None
    attempts: int
    dead_since: datetime


@dataclass(frozen=True, slots=True)
class ReplaySkip:
    event_id: UUID
    why: ReplaySkipReason


@dataclass(frozen=True, slots=True)
class ReplayResult:
    replayed: int
    skipped: tuple[ReplaySkip, ...]
    audit_id: int


@dataclass(frozen=True, slots=True)
class EnginePreview:
    """What a mutating chat tool shows before the person confirms."""

    what: str
    before: str
    after: str
    in_flight: int
    expected_version: int
    details: tuple[tuple[str, str], ...]
