"""OpenTelemetry tracing with sanitised attributes.

The provider is held in a module-level holder and the global OTel provider is never set: that call
is set-once and would break test isolation. With no OTLP endpoint configured the provider has no
span processor, so spans are exported nowhere but trace ids still exist for log correlation.
"""

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Final

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span, Status, StatusCode

from cashapp.domain.stages import Stage
from cashapp.observability.redaction import sanitize_mapping
from cashapp.settings import Settings

_INSTRUMENTATION_NAME: Final = "cashapp"

_provider: TracerProvider = TracerProvider(resource=Resource.create({"service.name": "cashapp"}))


def configure_tracing(
    settings: Settings, *, service_name: str = "cashapp", exporter: SpanExporter | None = None
) -> TracerProvider:
    """Build and install the tracer provider.

    An OTLP exporter is attached only when ``observability.otlp_endpoint`` is set; ``exporter``
    (tests) gets a synchronous processor. Otherwise no processor is attached.
    """
    global _provider
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = settings.observability.otlp_endpoint
    if endpoint is not None:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    elif exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    _provider = provider
    return provider


@contextmanager
def use_tracer_provider(provider: TracerProvider) -> Generator[None]:
    """Swap the provider for the duration of the block (tests)."""
    global _provider
    previous = _provider
    _provider = provider
    try:
        yield
    finally:
        _provider = previous


class SafeSpan:
    """A span whose attributes always pass through the shared sanitiser."""

    def __init__(self, inner: Span) -> None:
        self._inner = inner

    def set(self, **attrs: object) -> None:
        for key, value in sanitize_mapping(attrs).items():
            self._inner.set_attribute(key, value)

    @property
    def trace_id(self) -> str | None:
        context = self._inner.get_span_context()
        return trace.format_trace_id(context.trace_id) if context.is_valid else None


@contextmanager
def span(name: str, **attrs: object) -> Generator[SafeSpan]:
    """Run a block inside a span. Exceptions are recorded by class name only and re-raised."""
    tracer = _provider.get_tracer(_INSTRUMENTATION_NAME)
    started = time.monotonic()
    with tracer.start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as inner:
        safe = SafeSpan(inner)
        safe.set(**attrs)
        try:
            yield safe
        except BaseException as exc:
            inner.set_attribute("error.type", type(exc).__name__)
            inner.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
        finally:
            inner.set_attribute("latency_ms", round((time.monotonic() - started) * 1000, 3))


def station_span(stage: Stage | str) -> str:
    name = stage.value if isinstance(stage, Stage) else stage
    return f"station.{name.lower()}"


def fusion_span(method: str) -> str:
    return f"fusion.{method}"


def llm_span(role: str) -> str:
    return f"llm.{role}"


def current_trace_id() -> str | None:
    """The 32-hex trace id of the active span, or None when no valid span is active."""
    context = trace.get_current_span().get_span_context()
    return trace.format_trace_id(context.trace_id) if context.is_valid else None
