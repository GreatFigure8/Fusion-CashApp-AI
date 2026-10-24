"""JSON logging on stdout. Every line carries the item context; every handler redacts."""

import logging
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Final, TextIO

from pythonjsonlogger.json import JsonFormatter

from cashapp.api.request_context import get_request_id
from cashapp.observability.context import current_item_context
from cashapp.observability.redaction import RedactionFilter
from cashapp.observability.tracing import current_trace_id

LOG_FIELDS: Final = (
    "timestamp",
    "level",
    "logger",
    "message",
    "service",
    "work_item_id",
    "stage",
    "attempt",
    "trace_id",
    "request_id",
)

# Libraries whose own handlers are removed so their lines come out as redacted JSON too.
_ROUTED_LOGGERS: Final = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "oci")
# Their DEBUG lines can carry request bodies.
_WARNING_FLOOR: Final = ("httpx", "oci")


class ContextFilter(logging.Filter):
    """Fill the item-context keys, the trace id fallback and the request id."""

    def filter(self, record: logging.LogRecord) -> bool:
        item = current_item_context()
        record.work_item_id = item.work_item_id
        record.stage = item.stage
        record.attempt = item.attempt
        record.trace_id = item.trace_id if item.trace_id is not None else current_trace_id()
        record.request_id = get_request_id()
        return True


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return "<mapping>"
    return f"<{type(value).__name__}>"


class CashappJsonFormatter(JsonFormatter):
    """Fixed keys first, UTC ISO-8601 timestamps, absent values as JSON null."""

    def __init__(self, *, service_name: str = "cashapp") -> None:
        super().__init__(json_default=_json_default)  # pyright: ignore[reportUnknownMemberType]
        self._service_name = service_name

    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_data, record, message_dict)
        fixed: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service_name,
            "work_item_id": getattr(record, "work_item_id", None),
            "stage": getattr(record, "stage", None),
            "attempt": getattr(record, "attempt", None),
            "trace_id": getattr(record, "trace_id", None),
            "request_id": getattr(record, "request_id", None),
        }
        extras = {key: value for key, value in log_data.items() if key not in fixed}
        log_data.clear()
        log_data.update(fixed)
        log_data.update(extras)


def build_json_handler(stream: TextIO, *, service_name: str = "cashapp") -> logging.Handler:
    """The single place a log handler is built: context, then redaction, then JSON."""
    handler = logging.StreamHandler(stream)
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactionFilter())
    handler.setFormatter(CashappJsonFormatter(service_name=service_name))
    return handler


DEFAULT_LEVEL: Final = "INFO"


def resolve_level(level: str) -> int:
    """The numeric level for a name; a bad name falls back to INFO with a warning.

    Resolved before it is applied: `setLevel` with a bad name raises after the handlers are gone.
    """
    resolved = logging.getLevelNamesMapping().get(level.upper())
    if resolved is not None:
        return resolved
    logging.getLogger(__name__).warning(
        "unknown log level; using INFO", extra={"requested_level": str(level)[:20]}
    )
    return logging.INFO


def configure_logging_bootstrap(*, service_name: str = "cashapp") -> None:
    """INFO to stderr, before settings are read, so the loader's own warnings land somewhere."""
    configure_logging(DEFAULT_LEVEL, stream=sys.stderr, service_name=service_name)


def configure_logging(
    level: str = DEFAULT_LEVEL, *, stream: TextIO | None = None, service_name: str = "cashapp"
) -> None:
    """Install JSON logging on the root logger. Idempotent: calling twice leaves one handler."""
    numeric_level = resolve_level(level)
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    target = stream if stream is not None else sys.stderr
    root.addHandler(build_json_handler(target, service_name=service_name))
    root.setLevel(numeric_level)
    for name in _ROUTED_LOGGERS:
        routed = logging.getLogger(name)
        for existing in list(routed.handlers):
            routed.removeHandler(existing)
        routed.propagate = True
    for name in _WARNING_FLOOR:
        floor = logging.getLogger(name)
        if floor.getEffectiveLevel() < logging.WARNING:
            floor.setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """A plain stdlib logger. Pass structured data through ``extra=``, never in the message."""
    return logging.getLogger(name)
