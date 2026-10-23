"""The one sanitiser for everything that leaves the process as telemetry.

Raw artifacts, prompts and model output are never logged in full (CLAUDE.md, Conventions). Log
records and span attributes both pass through this module, so there is a single deny-list and a
single set of rules:

- a value under a denied key is replaced by ``[REDACTED]`` (the key stays, so a reader sees that
  something was there);
- a string over ``MAX_STRING_LEN`` characters becomes a length-and-hash marker;
- bytes and Pydantic models are never formatted, only described by size or class name;
- unknown objects are described by type name, never by ``str()`` or ``repr()``.

A short piece of personal data typed into a message literal (``f"paid by {name}"``) cannot be
detected. The convention for every caller is: IDs and counts go in ``extra=``, never remittance
content in the message.
"""

import hashlib
import logging
import os
import traceback
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final, cast

from pydantic import BaseModel

DENY_LIST: Final[frozenset[str]] = frozenset(
    {
        "payload",
        "content",
        "artifact",
        "prompt",
        "output",
        "body",
        "text",
        "payer_name",
        "email",
        "subject",
        "raw",
    }
)
MAX_STRING_LEN: Final = 200
MAX_DEPTH: Final = 5
REDACTED: Final = "[REDACTED]"

AttrValue = (
    str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]
)

_REDACTED_FLAG: Final = "_cashapp_redacted"
_STANDARD_RECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        *vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)),
        "message",
        "asctime",
        "taskName",
        _REDACTED_FLAG,
    }
)
_DENY_SUFFIXES: Final[tuple[str, ...]] = tuple(f"_{word}" for word in DENY_LIST)


def is_denied_key(key: str) -> bool:
    """True when the lower-cased key is a deny word or ends with ``_<deny word>``.

    ``email_body`` and ``raw_text`` are denied; ``output_tokens`` and ``content_hash`` are not.
    """
    lowered = key.lower()
    return lowered in DENY_LIST or lowered.endswith(_DENY_SUFFIXES)


def truncation_marker(value: str) -> str:
    """Describe a long string by its length and a short hash, never by its content."""
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"<truncated len={len(value)} sha256={digest}>"


def sanitize_value(value: object, *, depth: int = 0) -> object:
    """Return a log-safe copy of ``value``. Containers are walked to ``MAX_DEPTH``."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, Enum):
        return sanitize_value(value.value, depth=depth)
    if isinstance(value, str):
        return truncation_marker(value) if len(value) > MAX_STRING_LEN else value
    if isinstance(value, bytes | bytearray):
        return f"<bytes len={len(value)}>"
    if isinstance(value, memoryview):
        return f"<bytes len={value.nbytes}>"
    if isinstance(value, BaseModel):
        return f"<model {type(value).__name__}>"
    if isinstance(value, Decimal | datetime | date):
        return value
    if isinstance(value, Mapping):
        if depth >= MAX_DEPTH:
            return "<max depth>"
        mapping: Mapping[object, object] = value  # pyright: ignore[reportUnknownVariableType]
        return {
            str(key): REDACTED if is_denied_key(str(key)) else sanitize_value(item, depth=depth + 1)
            for key, item in mapping.items()
        }
    if isinstance(value, list | tuple):
        if depth >= MAX_DEPTH:
            return "<max depth>"
        items = cast("Sequence[object]", value)
        return [sanitize_value(item, depth=depth + 1) for item in items]
    return f"<{type(value).__name__}>"


def _to_attr_scalar(value: object) -> str | bool | int | float:
    if isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _to_attr_value(value: object) -> AttrValue | None:
    if value is None:
        return None
    if isinstance(value, list):
        items: list[object] = value  # pyright: ignore[reportUnknownVariableType]
        scalars = [_to_attr_scalar(item) for item in items]
        if len({type(item) for item in scalars}) <= 1:
            return scalars  # pyright: ignore[reportReturnType]
        return [str(item) for item in scalars]
    if isinstance(value, dict):
        return "<mapping>"
    return _to_attr_scalar(value)


def sanitize_mapping(attrs: Mapping[str, object]) -> dict[str, AttrValue]:
    """Sanitise span attributes: same deny-list and rules, output restricted to OTel-legal types."""
    clean: dict[str, AttrValue] = {}
    for key, value in attrs.items():
        converted = (
            REDACTED if is_denied_key(key) else _to_attr_value(sanitize_value(value, depth=1))
        )
        if converted is not None:
            clean[key] = converted
    return clean


def _safe_args(args: object) -> object:
    if isinstance(args, tuple):
        arg_tuple: tuple[object, ...] = args  # pyright: ignore[reportUnknownVariableType]
        return tuple(sanitize_value(arg) for arg in arg_tuple)
    if isinstance(args, Mapping):
        arg_map: Mapping[object, object] = args  # pyright: ignore[reportUnknownVariableType]
        return {str(key): sanitize_value(item) for key, item in arg_map.items()}
    return args


def _frames(exc_info: tuple[Any, Any, Any]) -> str:
    """Frames as ``file:line in function``: no source lines, no locals, no exception message."""
    tb = exc_info[2]
    if tb is None:
        return ""
    return " | ".join(
        f"{os.path.basename(frame.filename)}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(tb)
    )


class RedactionFilter(logging.Filter):
    """Attached to every handler. Mutates the record in place; never drops it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, _REDACTED_FLAG, False):
            return True
        # Format the message from sanitised args only, then sanitise the result.
        record.args = _safe_args(record.args)  # type: ignore[assignment]
        if not isinstance(record.msg, str):
            record.msg = sanitize_value(record.msg)
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            message = "<unformattable log message>"
        record.msg = sanitize_value(message)
        record.args = ()
        # Exceptions: type and frames only; the message is sanitised and kept separately.
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            record.__dict__["exc_type"] = type(exc).__name__
            record.__dict__["stack"] = _frames(record.exc_info)
            record.__dict__["exc_message"] = sanitize_value(str(exc))
        record.exc_info = None
        record.exc_text = None
        # Extras (every non-standard attribute).
        for name in [n for n in record.__dict__ if n not in _STANDARD_RECORD_ATTRS]:
            record.__dict__[name] = (
                REDACTED if is_denied_key(name) else sanitize_value(record.__dict__[name])
            )
        setattr(record, _REDACTED_FLAG, True)
        return True
