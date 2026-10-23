"""Structured logs, traces and metrics per work item, with remittance content redacted."""

from typing import TYPE_CHECKING

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
    configure_logging_bootstrap,
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

if TYPE_CHECKING:
    from cashapp.services.runtime_settings import RuntimeSettings


def configure_observability_bootstrap(*, service_name: str) -> None:
    """Logging at INFO to stderr before the database is reachable."""
    configure_logging_bootstrap(service_name=service_name)


def reconfigure_observability(runtime: "RuntimeSettings", *, service_name: str) -> None:
    """Apply the DB-stored level and trace endpoint once `RuntimeSettings.start()` has run."""
    config = runtime.observability()
    configure_logging(config.log_level, service_name=service_name)
    configure_tracing(config.otlp_endpoint, service_name=service_name)


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
    "configure_logging_bootstrap",
    "configure_observability_bootstrap",
    "configure_tracing",
    "current_item_context",
    "current_trace_id",
    "fusion_span",
    "get_logger",
    "is_denied_key",
    "llm_span",
    "reconfigure_observability",
    "sanitize_mapping",
    "sanitize_value",
    "span",
    "station_span",
    "truncation_marker",
    "use_tracer_provider",
]
