"""Fixtures for asserting on logs, spans and metrics: ``capture_logs``, ``capture_spans``,
``in_memory_metrics``. Registered through ``pytest_plugins`` in ``tests/conftest.py``."""

import json
import logging
from collections.abc import Iterator
from io import StringIO
from typing import Any, SupportsIndex, overload

import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from cashapp.observability.logging import build_json_handler
from cashapp.observability.metrics import InMemoryMetrics
from cashapp.observability.tracing import use_tracer_provider
from tests.support.clock import FrozenClock


class LiveLogRecords(list[dict[str, Any]]):
    """A list of parsed JSON log lines, re-parsed from the stream on every access."""

    def __init__(self, stream: StringIO) -> None:
        super().__init__()
        self._stream = stream

    def _lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self._stream.getvalue().splitlines() if line.strip()]

    def __iter__(self) -> Iterator[dict[str, Any]]:  # type: ignore[override]
        return iter(self._lines())

    def __len__(self) -> int:
        return len(self._lines())

    @overload
    def __getitem__(self, index: SupportsIndex) -> dict[str, Any]: ...
    @overload
    def __getitem__(self, index: slice) -> list[dict[str, Any]]: ...
    def __getitem__(self, index: SupportsIndex | slice) -> dict[str, Any] | list[dict[str, Any]]:
        return self._lines()[index]

    def __bool__(self) -> bool:
        return bool(self._lines())


@pytest.fixture
def capture_logs() -> Iterator[list[dict[str, Any]]]:
    stream = StringIO()
    handler = build_json_handler(stream)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield LiveLogRecords(stream)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


@pytest.fixture
def capture_spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "cashapp-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with use_tracer_provider(provider):
        yield exporter


@pytest.fixture
def in_memory_metrics() -> InMemoryMetrics:
    return InMemoryMetrics(clock=FrozenClock())
