"""Structured logs, traces and metrics per work item, with remittance content redacted."""

from cashapp.observability.context import (
    ItemContext,
    bind_item_context,
    current_item_context,
)
from cashapp.observability.logging import (
    LOG_FIELDS,
    CashappJsonFormatter,
    ContextFilter,
    build_json_handler,
    configure_logging,
    get_logger,
)
from cashapp.observability.metrics import (
    InMemoryMetrics,
    MetricPoint,
    Metrics,
    MetricSink,
    MonitoringClientLike,
    OciMonitoringExporter,
    build_metrics,
)
from cashapp.observability.queue_stats import QueueStat, collect_queue_stats
from cashapp.observability.redaction import (
    DENY_LIST,
    MAX_STRING_LEN,
    REDACTED,
    AttrValue,
    RedactionFilter,
    is_denied_key,
    sanitize_mapping,
    sanitize_value,
    truncation_marker,
)
from cashapp.observability.tracing import (
    SafeSpan,
    configure_tracing,
    current_trace_id,
    fusion_span,
    llm_span,
    span,
    station_span,
    use_tracer_provider,
)
from cashapp.settings import Settings


def configure_observability(settings: Settings, *, service_name: str) -> None:
    """Logging and tracing for one process."""
    configure_logging(settings, service_name=service_name)
    configure_tracing(settings, service_name=service_name)


__all__ = [
    "DENY_LIST",
    "LOG_FIELDS",
    "MAX_STRING_LEN",
    "REDACTED",
    "AttrValue",
    "CashappJsonFormatter",
    "ContextFilter",
    "InMemoryMetrics",
    "ItemContext",
    "MetricPoint",
    "MetricSink",
    "Metrics",
    "MonitoringClientLike",
    "OciMonitoringExporter",
    "QueueStat",
    "RedactionFilter",
    "SafeSpan",
    "bind_item_context",
    "build_json_handler",
    "build_metrics",
    "collect_queue_stats",
    "configure_logging",
    "configure_observability",
    "configure_tracing",
    "current_item_context",
    "current_trace_id",
    "fusion_span",
    "get_logger",
    "is_denied_key",
    "llm_span",
    "sanitize_mapping",
    "sanitize_value",
    "span",
    "station_span",
    "truncation_marker",
    "use_tracer_provider",
]
