"""API contracts for engine control (pinned: the shell footer, the Engine screen and the chat read
these). Separate from the service result types; nothing returns an ORM model.
"""

from typing import Any, Literal, Self, get_args
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from cashapp.domain.engine import Station, StationState
from cashapp.services.engine.models import (
    DeadLetter,
    EngineActionResult,
    EngineAuditEntry,
    EngineStatus,
    PollerStatus,
    ReplayResult,
    StationStatus,
    ThrottleStatus,
)

StationName = Literal[
    "intake",
    "classify",
    "extract.reader_a",
    "extract.reader_b",
    "adjudicate",
    "validate",
    "resolve_customer",
    "match_receipt",
    "await_receipt",
    "match_lines",
    "apply",
    "write_back",
]
if set(get_args(StationName)) != {s.value for s in Station}:  # a new Station needs a new name
    raise RuntimeError("StationName is out of step with the Station enum")


class StationOut(BaseModel):
    name: StationName
    state: Literal["RUNNING", "PAUSED", "DRAINING", "DRAINED"]
    lag: int | None = Field(description="Messages not yet committed; null when unknown.")
    throughput_per_min: float = Field(description="Mean over the last five minutes.")
    dlq_depth: int
    in_flight: int
    limit: int
    saturated: bool = Field(description="in_flight is at or above limit.")
    waiting: int | None = Field(description="await_receipt only: items waiting for a receipt.")

    @classmethod
    def from_data(cls, data: StationStatus) -> Self:
        return cls(
            name=data.station.value,  # type: ignore[arg-type]
            state=data.state.value,  # type: ignore[arg-type]
            lag=data.lag,
            throughput_per_min=data.throughput_per_min,
            dlq_depth=data.dlq_depth,
            in_flight=data.in_flight,
            limit=data.limit,
            saturated=data.saturated,
            waiting=data.waiting,
        )


class PollerOut(BaseModel):
    name: Literal["intake-poller", "receipt-watcher"]
    interval_seconds: int
    last_beat_at: AwareDatetime | None
    healthy: bool

    @classmethod
    def from_data(cls, data: PollerStatus) -> Self:
        return cls(
            name=data.name,  # type: ignore[arg-type]
            interval_seconds=data.interval_seconds,
            last_beat_at=data.last_beat_at,
            healthy=data.healthy,
        )


class ThrottleOut(BaseModel):
    per_stage: dict[str, int]
    apply_per_receipt: int

    @classmethod
    def from_data(cls, data: ThrottleStatus) -> Self:
        return cls(per_stage=dict(data.per_stage), apply_per_receipt=data.apply_per_receipt)


class EngineStatusOut(BaseModel):
    bus_healthy: bool
    total_lag: int
    dlq_total: int
    pollers: list[PollerOut]
    region: str
    consumer_group: str
    stations: list[StationOut]
    throttle: ThrottleOut
    config_version: int = Field(description="Send this back as expected_version.")
    counts: dict[Literal["running", "paused", "draining", "drained"], int]
    generated_at: AwareDatetime

    @classmethod
    def from_data(cls, data: EngineStatus) -> Self:
        return cls(
            bus_healthy=data.bus_healthy,
            total_lag=data.total_lag,
            dlq_total=data.dlq_total,
            pollers=[PollerOut.from_data(p) for p in data.pollers],
            region=data.region,
            consumer_group=data.consumer_group,
            stations=[StationOut.from_data(s) for s in data.stations],
            throttle=ThrottleOut.from_data(data.throttle),
            config_version=data.config_version,
            counts={
                state.value.lower(): data.counts.get(state, 0)  # type: ignore[misc]
                for state in StationState
            },
            generated_at=data.generated_at,
        )


class EngineActionIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=0)


class ThrottleIn(EngineActionIn):
    per_stage: int = Field(
        ge=1, le=32, description='Written as concurrency.per_stage {"*": n}; other entries clamped.'
    )
    apply_per_receipt: int = Field(ge=1, le=8)


class EngineAuditOut(BaseModel):
    id: int
    at: AwareDatetime
    actor_id: str
    actor_name: str
    actor_role: str
    action: Literal["PAUSE", "RESUME", "DRAIN", "THROTTLE", "REPLAY"]
    stations: list[StationName]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str
    config_version: int
    source: Literal["api", "chat"]

    @classmethod
    def from_data(cls, data: EngineAuditEntry) -> Self:
        return cls(
            id=data.id,
            at=data.at,
            actor_id=data.actor_id,
            actor_name=data.actor_name,
            actor_role=data.actor_role,
            action=data.action.value,  # type: ignore[arg-type]
            stations=[s.value for s in data.stations],  # type: ignore[misc]
            before=dict(data.before) if data.before is not None else None,
            after=dict(data.after) if data.after is not None else None,
            reason=data.reason,
            config_version=data.config_version,
            source=data.source,
        )


class EngineAuditPage(BaseModel):
    items: list[EngineAuditOut]
    total: int
    offset: int
    limit: int


class EngineActionOut(BaseModel):
    status: EngineStatusOut
    audit: EngineAuditOut

    @classmethod
    def from_data(cls, data: EngineActionResult) -> Self:
        return cls(
            status=EngineStatusOut.from_data(data.status),
            audit=EngineAuditOut.from_data(data.audit),
        )


class DeadLetterOut(BaseModel):
    event_id: UUID
    stage: StationName
    item_id: int | None
    error_code: str | None
    attempts: int
    dead_since: AwareDatetime

    @classmethod
    def from_data(cls, data: DeadLetter) -> Self:
        return cls(
            event_id=data.event_id,
            stage=data.station.value,  # type: ignore[arg-type]
            item_id=data.item_id,
            error_code=data.error_code,
            attempts=data.attempts,
            dead_since=data.dead_since,
        )


class DeadLetterPage(BaseModel):
    items: list[DeadLetterOut]
    total: int
    offset: int
    limit: int


class ReplayIn(BaseModel):
    event_ids: list[UUID] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1000)


class ReplaySkipOut(BaseModel):
    event_id: UUID
    why: Literal["locked", "done", "already_replayed", "moved_on", "not_found"]


class ReplayOut(BaseModel):
    replayed: int
    skipped: list[ReplaySkipOut]
    audit_id: int

    @classmethod
    def from_data(cls, data: ReplayResult) -> Self:
        return cls(
            replayed=data.replayed,
            skipped=[ReplaySkipOut(event_id=s.event_id, why=s.why) for s in data.skipped],
            audit_id=data.audit_id,
        )
