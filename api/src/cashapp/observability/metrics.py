"""Metrics facade and the OCI Monitoring exporter.

There are exactly two sinks: the real ``OciMonitoringExporter`` and the in-memory fake behind
``InMemoryMetrics``. Dimension values always come from enums or configuration, never free text, so
no personal data reaches OCI Monitoring.

Unverified against live: the ingestion endpoint host, the 50-streams-per-call limit, namespace rules
(lower-case, no ``oci_``/``oracle_`` prefix) and the datapoint age window (about two hours past).
"""

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Protocol

from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import ItemState, Stage
from cashapp.settings import oci_signer

if TYPE_CHECKING:
    from cashapp.services.runtime_settings import RuntimeSettings

_log = logging.getLogger(__name__)

INGESTION_ENDPOINT: Final = "https://telemetry-ingestion.us-ashburn-1.oraclecloud.com"
REGION: Final = "us-ashburn-1"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    name: str
    value: float
    dimensions: Mapping[str, str]
    timestamp: datetime
    unit: str | None = None


class MetricSink(Protocol):
    async def export(self, points: Sequence[MetricPoint]) -> None: ...


def _label(value: Stage | ItemState | ErrorCode | str) -> str:
    return value.value if isinstance(value, Stage | ItemState | ErrorCode) else value


class Metrics:
    """The one metrics facade. Methods buffer points; ``flush`` sends them and never raises."""

    def __init__(
        self, sink: MetricSink, *, clock: Clock | None = None, max_buffer: int = 10_000
    ) -> None:
        self._sink = sink
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._max_buffer = max_buffer
        self._buffer: deque[MetricPoint] = deque()
        self.dropped = 0

    def _add(
        self, name: str, value: float, dimensions: Mapping[str, str], unit: str | None = None
    ) -> None:
        if len(self._buffer) >= self._max_buffer:
            self._buffer.popleft()
            self.dropped += 1
        self._buffer.append(
            MetricPoint(
                name=name,
                value=float(value),
                dimensions=dict(dimensions),
                timestamp=self._clock.now(),
                unit=unit,
            )
        )

    def stage_processed(self, stage: Stage | str, outcome: str, latency_s: float) -> None:
        dims = {"stage": _label(stage), "outcome": outcome}
        self._add("stage_processed", 1, dims, "count")
        self._add("stage_latency_seconds", latency_s, dims, "seconds")

    def stage_failed(self, stage: Stage | str, error_code: ErrorCode | str) -> None:
        self._add(
            "stage_failed", 1, {"stage": _label(stage), "error_code": _label(error_code)}, "count"
        )

    def queue_depth(
        self, stage: Stage | str, state: ItemState | str, count: int, oldest_age_s: float | None
    ) -> None:
        dims = {"stage": _label(stage), "state": _label(state)}
        self._add("queue_depth", count, dims, "count")
        if oldest_age_s is not None:
            self._add("queue_oldest_age_seconds", oldest_age_s, dims, "seconds")

    def bus_health(self, stage: Stage | str, lag: int, dlq_depth: int) -> None:
        dims = {"stage": _label(stage)}
        self._add("bus_consumer_lag", lag, dims, "count")
        self._add("bus_dlq_depth", dlq_depth, dims, "count")

    def llm_call(
        self, role: str, model: str, tokens_in: int, tokens_out: int, latency_ms: float
    ) -> None:
        dims = {"role": role, "model": model}
        self._add("llm_calls", 1, dims, "count")
        self._add("llm_tokens_in", tokens_in, dims, "count")
        self._add("llm_tokens_out", tokens_out, dims, "count")
        self._add("llm_latency_ms", latency_ms, dims, "milliseconds")

    async def flush(self) -> None:
        """Send the buffer to the sink. A sink error is logged (type, count only) and swallowed."""
        if not self._buffer:
            return
        batch = list(self._buffer)
        self._buffer.clear()
        try:
            await self._sink.export(batch)
        except Exception as exc:
            _log.warning(
                "metrics_export_failed",
                extra={"error_type": type(exc).__name__, "point_count": len(batch)},
            )


class _ListSink:
    def __init__(self) -> None:
        self.exported: list[MetricPoint] = []

    async def export(self, points: Sequence[MetricPoint]) -> None:
        self.exported.extend(points)


class InMemoryMetrics(Metrics):
    """Metrics whose sink is an in-memory list, for tests and the local environment."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._list_sink = _ListSink()
        super().__init__(self._list_sink, clock=clock)

    @property
    def exported(self) -> list[MetricPoint]:
        return self._list_sink.exported

    def points(self, name: str, **dims: str) -> list[MetricPoint]:
        """Buffered and exported points named ``name`` whose dimensions include ``dims``."""
        return [
            point
            for point in (*self._list_sink.exported, *self._buffer)
            if point.name == name and all(point.dimensions.get(k) == v for k, v in dims.items())
        ]

    def total(self, name: str, **dims: str) -> float:
        return sum(point.value for point in self.points(name, **dims))


class MonitoringClientLike(Protocol):
    def post_metric_data(self, post_metric_data_details: Any) -> Any: ...


@dataclass(slots=True)
class _Stream:
    name: str
    dimensions: Mapping[str, str]
    unit: str | None
    points: list[MetricPoint] = field(default_factory=lambda: [])


class OciMonitoringExporter:
    """Posts batched ``PostMetricData`` calls to OCI Monitoring, off the event loop."""

    MAX_STREAMS_PER_CALL: Final = 50

    def __init__(
        self, client: MonitoringClientLike, *, namespace: str, compartment_id: str
    ) -> None:
        self._client = client
        self._namespace = namespace
        self._compartment_id = compartment_id

    @classmethod
    def from_signer(
        cls, signer: Any, namespace: str, compartment_id: str
    ) -> "OciMonitoringExporter":
        """The signer comes from `settings.oci_signer`, which owns the environment reads."""
        import oci  # pyright: ignore[reportMissingTypeStubs]

        sdk: Any = oci
        client: MonitoringClientLike = sdk.monitoring.MonitoringClient(
            config={"region": REGION}, signer=signer, service_endpoint=INGESTION_ENDPOINT
        )
        return cls(client, namespace=namespace, compartment_id=compartment_id)

    def _details(self, streams: Sequence[_Stream]) -> Any:
        import oci  # pyright: ignore[reportMissingTypeStubs]

        models: Any = oci.monitoring.models
        data = [
            models.MetricDataDetails(
                namespace=self._namespace,
                compartment_id=self._compartment_id,
                name=stream.name,
                dimensions=dict(stream.dimensions),
                metadata={"unit": stream.unit} if stream.unit is not None else None,
                datapoints=[
                    models.Datapoint(timestamp=point.timestamp, value=point.value)
                    for point in stream.points
                ],
            )
            for stream in streams
        ]
        return models.PostMetricDataDetails(metric_data=data)

    def _post(self, streams: Sequence[_Stream]) -> Any:
        return self._client.post_metric_data(self._details(streams))

    async def export(self, points: Sequence[MetricPoint]) -> None:
        grouped: dict[tuple[str, tuple[tuple[str, str], ...]], _Stream] = defaultdict(
            lambda: _Stream("", {}, None)
        )
        for point in points:
            key = (point.name, tuple(sorted(point.dimensions.items())))
            stream = grouped[key]
            if not stream.points:
                stream.name, stream.dimensions, stream.unit = (
                    point.name,
                    point.dimensions,
                    point.unit,
                )
            stream.points.append(point)
        streams = list(grouped.values())
        size = self.MAX_STREAMS_PER_CALL
        for start in range(0, len(streams), size):
            response = await asyncio.to_thread(self._post, streams[start : start + size])
            data = getattr(response, "data", response)
            failed = getattr(data, "failed_metrics_count", 0)
            if isinstance(failed, int) and failed > 0:
                _log.warning(
                    "oci_monitoring_failed_metrics", extra={"failed_metrics_count": failed}
                )


def build_metrics(runtime: "RuntimeSettings") -> Metrics:
    """In-memory sink locally; OCI Monitoring everywhere else."""
    if runtime.env == "local":
        return InMemoryMetrics()
    signer = oci_signer(runtime.settings)
    if signer is None:
        raise RuntimeError("no OCI signer is available for OCI Monitoring")
    return Metrics(
        OciMonitoringExporter.from_signer(
            signer,
            runtime.observability().oci_monitoring_namespace,
            runtime.oci_genai().compartment_ocid,
        )
    )
