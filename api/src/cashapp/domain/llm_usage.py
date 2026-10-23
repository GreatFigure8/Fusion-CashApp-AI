"""LLM usage ledger vocabulary: roles, outcomes, grouping, the usage entry and 6 dp USD."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema
from pydantic_core import PydanticCustomError

__all__ = [
    "LlmRole",
    "UsageEntry",
    "UsageGroupBy",
    "UsageOutcome",
    "UsdStr",
    "station_of",
    "to_usd",
]

_MICRO = Decimal("0.000001")
_STATION_MAX = 40


class LlmRole(StrEnum):
    READER_A = "reader_a"
    READER_B = "reader_b"
    ADJUDICATOR = "adjudicator"
    WORKHORSE = "workhorse"


class UsageOutcome(StrEnum):
    OK = "ok"
    REFUSED = "refused"
    ERROR = "error"
    TIMEOUT = "timeout"


class UsageGroupBy(StrEnum):
    STATION = "station"
    MODEL = "model"


def to_usd(value: Decimal | int | str) -> Decimal:
    """Quantise to 6 dp with ROUND_HALF_UP. Floats are refused: they carry binary error."""
    if isinstance(value, bool | float):
        raise TypeError("to_usd does not accept float or bool; pass Decimal, str or int")
    return Decimal(value).quantize(_MICRO, rounding=ROUND_HALF_UP)


def station_of(purpose: str) -> str:
    """The station is the purpose text before the first dot, lower-cased, at most 40 chars."""
    return purpose.partition(".")[0].lower()[:_STATION_MAX]


def _coerce_usd(value: Any) -> Decimal:
    if isinstance(value, float):
        value = str(value)
    try:
        return to_usd(value)
    except (TypeError, ArithmeticError, ValueError) as exc:
        raise PydanticCustomError("usd_invalid", "Value is not a valid USD amount") from exc


UsdStr = Annotated[
    Decimal,
    BeforeValidator(_coerce_usd),
    PlainSerializer(lambda d: f"{d:.6f}", return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{6}$", "examples": ["0.012345"]}),
]


@dataclass(frozen=True, slots=True)
class UsageEntry:
    """One model call. Ids, counts and codes only: never prompt, artifact or output text."""

    role: LlmRole
    provider: str
    model_id: str
    purpose: str
    station: str
    work_item_id: int | None
    prompt_version: str | None
    schema_version: str | None
    effort: str | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    outcome: UsageOutcome
    error_code: str | None
    occurred_at: datetime  # tz-aware UTC
