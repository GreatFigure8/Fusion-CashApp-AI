"""The engine's stations: the one catalogue the control API, the pause gate and the UI read.

A station is a unit a person can pause, drain or throttle. There are twelve (design.md section
3.3). They are derived from ``Stage`` plus the two extraction reader slots plus the
receipt-arrived consumer, and each one names the consumer it gates, so a pause really holds the
thing it says it holds. Pure: no I/O, no framework imports.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from cashapp.domain.extraction import ReaderSlot
from cashapp.domain.stages import Stage


class Station(StrEnum):
    INTAKE = "intake"
    CLASSIFY = "classify"
    EXTRACT_READER_A = "extract.reader_a"
    EXTRACT_READER_B = "extract.reader_b"
    ADJUDICATE = "adjudicate"
    VALIDATE = "validate"
    RESOLVE_CUSTOMER = "resolve_customer"
    MATCH_RECEIPT = "match_receipt"
    AWAIT_RECEIPT = "await_receipt"
    MATCH_LINES = "match_lines"
    APPLY = "apply"
    WRITE_BACK = "write_back"


class StationState(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DRAINING = "DRAINING"
    DRAINED = "DRAINED"


class EngineAction(StrEnum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    DRAIN = "DRAIN"
    THROTTLE = "THROTTLE"
    REPLAY = "REPLAY"


class ConsumerKind(StrEnum):
    STAGE = "stage"  # a StageConsumer on one stage's topic
    RECEIPT_ARRIVED = "receipt_arrived"  # the receipt-arrived consumer
    INTAKE = "intake"  # the intake poller's cycle


@dataclass(frozen=True, slots=True)
class ConsumerRef:
    """What a station gates: the identity a runner passes to the pause gate."""

    kind: ConsumerKind
    stage: Stage | None = None

    @classmethod
    def for_stage(cls, stage: Stage) -> "ConsumerRef":
        return cls(ConsumerKind.STAGE, stage)

    @classmethod
    def receipt_arrived(cls) -> "ConsumerRef":
        return cls(ConsumerKind.RECEIPT_ARRIVED)

    @classmethod
    def intake_poller(cls) -> "ConsumerRef":
        return cls(ConsumerKind.INTAKE)


@dataclass(frozen=True, slots=True)
class StationSpec:
    station: Station
    consumer: ConsumerRef
    reader_slot: ReaderSlot | None = None
    # Further consumers held by the same pause (fast path rides with receipt matching).
    also_gates: tuple[ConsumerRef, ...] = ()
    # The stage whose items this station works on (None for the receipt consumer).
    stage: Stage | None = None

    @property
    def consumers(self) -> tuple[ConsumerRef, ...]:
        return (self.consumer, *self.also_gates)


STATIONS: Final[tuple[StationSpec, ...]] = (
    StationSpec(Station.INTAKE, ConsumerRef.intake_poller(), stage=Stage.INTAKE),
    StationSpec(Station.CLASSIFY, ConsumerRef.for_stage(Stage.CLASSIFY), stage=Stage.CLASSIFY),
    StationSpec(
        Station.EXTRACT_READER_A,
        ConsumerRef.for_stage(Stage.EXTRACT),
        reader_slot=ReaderSlot.A,
        stage=Stage.EXTRACT,
    ),
    StationSpec(
        Station.EXTRACT_READER_B,
        ConsumerRef.for_stage(Stage.EXTRACT),
        reader_slot=ReaderSlot.B,
        stage=Stage.EXTRACT,
    ),
    StationSpec(
        Station.ADJUDICATE, ConsumerRef.for_stage(Stage.ADJUDICATE), stage=Stage.ADJUDICATE
    ),
    StationSpec(Station.VALIDATE, ConsumerRef.for_stage(Stage.VALIDATE), stage=Stage.VALIDATE),
    StationSpec(
        Station.RESOLVE_CUSTOMER,
        ConsumerRef.for_stage(Stage.RESOLVE_CUSTOMER),
        stage=Stage.RESOLVE_CUSTOMER,
    ),
    StationSpec(
        Station.MATCH_RECEIPT,
        ConsumerRef.for_stage(Stage.MATCH_RECEIPT),
        also_gates=(ConsumerRef.for_stage(Stage.FAST_PATH),),
        stage=Stage.MATCH_RECEIPT,
    ),
    StationSpec(Station.AWAIT_RECEIPT, ConsumerRef.receipt_arrived()),
    StationSpec(
        Station.MATCH_LINES, ConsumerRef.for_stage(Stage.MATCH_LINES), stage=Stage.MATCH_LINES
    ),
    StationSpec(Station.APPLY, ConsumerRef.for_stage(Stage.APPLY), stage=Stage.APPLY),
    StationSpec(
        Station.WRITE_BACK, ConsumerRef.for_stage(Stage.WRITE_BACK), stage=Stage.WRITE_BACK
    ),
)

_SPEC_BY_STATION: Final[dict[Station, StationSpec]] = {spec.station: spec for spec in STATIONS}
if len(_SPEC_BY_STATION) != len(Station):  # a new Station needs a StationSpec
    raise RuntimeError("STATIONS is out of step with the Station enum")

# Reader B shares EXTRACT with reader A; a dead letter on EXTRACT is shown on reader A.
_PRIMARY_STATION_OF_STAGE: Final[dict[Stage, Station]] = {
    Stage.INTAKE: Station.INTAKE,
    Stage.CLASSIFY: Station.CLASSIFY,
    Stage.EXTRACT: Station.EXTRACT_READER_A,
    Stage.ADJUDICATE: Station.ADJUDICATE,
    Stage.VALIDATE: Station.VALIDATE,
    Stage.RESOLVE_CUSTOMER: Station.RESOLVE_CUSTOMER,
    Stage.FAST_PATH: Station.MATCH_RECEIPT,
    Stage.MATCH_RECEIPT: Station.MATCH_RECEIPT,
    Stage.MATCH_LINES: Station.MATCH_LINES,
    Stage.APPLY: Station.APPLY,
    Stage.WRITE_BACK: Station.WRITE_BACK,
}

ENGINE_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "engine.paused_stations",
    "engine.draining_stations",
    "concurrency.per_stage",
    "concurrency.apply_per_receipt",
)
"""The keys whose versions add up to the engine's ``config_version`` (the optimistic check)."""

PAUSE_RECHECK_SECONDS: Final = 1.0
"""How often a paused runner looks at the pause list again."""

PER_STAGE_BOUNDS: Final = (1, 32)
APPLY_PER_RECEIPT_BOUNDS: Final = (1, 8)


def spec_for(station: Station) -> StationSpec:
    return _SPEC_BY_STATION[station]


def parse_station(value: str) -> Station | None:
    """The station named ``value``, or None."""
    try:
        return Station(value)
    except ValueError:
        return None


def station_of_stage(stage: Stage) -> Station | None:
    """The station that shows a dead letter or a work count for ``stage``."""
    return _PRIMARY_STATION_OF_STAGE.get(stage)


def dead_letter_stages() -> tuple[Stage, ...]:
    """Every stage that can dead-letter an event (the stages with a station)."""
    return tuple(_PRIMARY_STATION_OF_STAGE)


def stages_of_station(station: Station) -> tuple[Stage, ...]:
    """Every stage whose dead letters belong to ``station``."""
    return tuple(s for s, owner in _PRIMARY_STATION_OF_STAGE.items() if owner is station)


def gating_stations(consumer: ConsumerRef) -> frozenset[Station]:
    """The stations whose pause holds ``consumer``."""
    return frozenset(spec.station for spec in STATIONS if consumer in spec.consumers)


def consumer_stages() -> frozenset[Stage]:
    """Every stage whose consumer some station gates."""
    return frozenset(
        ref.stage
        for spec in STATIONS
        for ref in spec.consumers
        if ref.kind is ConsumerKind.STAGE and ref.stage is not None
    )
