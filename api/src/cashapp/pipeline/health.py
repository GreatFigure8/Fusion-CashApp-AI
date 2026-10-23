"""Bus health for the metrics exporter: consumer lag and dead-letter depth per stage."""

from collections.abc import Sequence
from typing import TypedDict

from cashapp.domain.stages import PIPELINE_ORDER, Stage
from cashapp.pipeline.bus import EventBus
from cashapp.pipeline.events import TopicNamer

CONSUMED_STAGES: tuple[Stage, ...] = tuple(
    stage for stage in PIPELINE_ORDER if stage not in (Stage.INTAKE, Stage.DONE)
)
"""Stages that have a consumer: everything except intake (poller-driven) and done."""


class StageBusHealth(TypedDict):
    lag: int
    dlq_depth: int


class BusHealth:
    def __init__(
        self, bus: EventBus, namer: TopicNamer, stages: Sequence[Stage] = CONSUMED_STAGES
    ) -> None:
        self._bus = bus
        self._namer = namer
        self._stages = tuple(stages)

    async def snapshot(self) -> dict[Stage, StageBusHealth]:
        """Lag of each stage's main topic and the depth of its DLQ; ``-1`` means unknown."""
        result: dict[Stage, StageBusHealth] = {}
        for stage in self._stages:
            result[stage] = StageBusHealth(
                lag=await self._bus.consumer_lag(self._namer.for_stage(stage)),
                dlq_depth=await self._bus.dlq_depth(stage),
            )
        return result
