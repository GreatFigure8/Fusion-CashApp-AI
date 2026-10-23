"""Matching lab vocabulary: which keys a candidate may change, their hard bounds, ids, outcomes.

Pure: no I/O and no framework imports. The lab policy is fail-closed: only the keys listed in
``LAB_KEYS`` can be proposed, and each has a hard bound on top of the registry's own validation.
"""

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Final, cast

from cashapp.domain import config_keys as ck

LAB_KEYS: Final[tuple[str, ...]] = (
    ck.MATCHING_DATE_WINDOW_DAYS.name,
    ck.MATCHING_TOLERANCES.name,
    ck.MATCHING_BANK_FEE_BANDS.name,
    ck.MATCHING_SCORER_WEIGHTS.name,
    ck.MATCHING_MIN_SCORE.name,
)

MAX_DATE_WINDOW_DAYS: Final = 30
MAX_TOLERANCE: Final = Decimal("5.00")
MAX_BANK_FEE: Final = Decimal("100.00")
MAX_WEIGHT: Final = 10.0
MAX_MIN_SCORE: Final = 10.0

AUDIT_LABEL_PROMOTE: Final = "lab.promote"
PROMOTE_REASON_MAX: Final = 1000
RATIONALE_MAX: Final = 2000
CSV_FORMULA_PREFIXES: Final = ("=", "+", "-", "@", "\t", "\r")


class ReplayStatus(StrEnum):
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    STALE = "STALE"  # computed on read, never stored


class CandidateStatus(StrEnum):
    OPEN = "OPEN"
    PROMOTED = "PROMOTED"
    DISCARDED = "DISCARDED"


class ReplayOutcome(StrEnum):
    MATCHED = "matched"
    NO_RECEIPT = "no_receipt"
    AMBIGUOUS = "ambiguous"
    VARIANCE = "variance"
    LINES_FAILED = "lines_failed"
    NO_INPUT = "no_input"


class ChangeKind(StrEnum):
    UNCHANGED = "unchanged"
    NEWLY_MATCHED = "newly_matched"
    NEWLY_FAILED = "newly_failed"
    NEWLY_AMBIGUOUS = "newly_ambiguous"
    OTHER = "other"  # moved between two non-matched outcomes


def classify_change(before: ReplayOutcome, after: ReplayOutcome) -> ChangeKind:
    """How the candidate config moved one item relative to live. ``no_input`` never counts."""
    if ReplayOutcome.NO_INPUT in (before, after) or before is after:
        return ChangeKind.UNCHANGED
    if after is ReplayOutcome.AMBIGUOUS:
        return ChangeKind.NEWLY_AMBIGUOUS
    if after is ReplayOutcome.MATCHED:
        return ChangeKind.NEWLY_MATCHED
    if before is ReplayOutcome.MATCHED:
        return ChangeKind.NEWLY_FAILED
    return ChangeKind.OTHER


_CANDIDATE_RE: Final = re.compile(r"^p_(\d{4,12})$")
_REPLAY_RE: Final = re.compile(r"^rp_(\d{4,12})$")


def format_candidate_id(number: int) -> str:
    return f"p_{number:04d}"


def format_replay_id(number: int) -> str:
    return f"rp_{number:04d}"


def parse_candidate_id(value: str) -> int | None:
    match = _CANDIDATE_RE.match(value)
    return int(match.group(1)) if match else None


def parse_replay_id(value: str) -> int | None:
    match = _REPLAY_RE.match(value)
    return int(match.group(1)) if match else None


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return cast("Mapping[str, Any]", value)
    return {}


def _bound_window(value: Any) -> list[str]:
    days = _number(value)
    if days is None or not 0 <= days <= MAX_DATE_WINDOW_DAYS:
        return [f"Must be between 0 and {MAX_DATE_WINDOW_DAYS} days"]
    return []


def _bound_tolerances(value: Any) -> list[str]:
    errors: list[str] = []
    for name, raw in _mapping(value).items():
        amount = _decimal(raw)
        if amount is None or not Decimal("0.00") <= amount <= MAX_TOLERANCE:
            errors.append(f"Tolerance for {name} must be between 0.00 and {MAX_TOLERANCE}")
    return errors


def _bound_bands(value: Any) -> list[str]:
    errors: list[str] = []
    bands: list[Any] = cast("list[Any]", value) if isinstance(value, list) else []
    for index, band in enumerate(bands):
        row = _mapping(band)
        low, high = _decimal(row.get("min_fee")), _decimal(row.get("max_fee"))
        if low is None or high is None or low < 0:
            errors.append(f"Band {index}: min_fee must be at least 0.00")
        elif high > MAX_BANK_FEE:
            errors.append(f"Band {index}: max_fee must be at most {MAX_BANK_FEE}")
    return errors


def _bound_weights(value: Any) -> list[str]:
    errors: list[str] = []
    for name, raw in _mapping(value).items():
        weight = _number(raw)
        if weight is None or not 0 <= weight <= MAX_WEIGHT:
            errors.append(f"Weight for {name} must be between 0 and {MAX_WEIGHT:g}")
    return errors


def _bound_min_score(value: Any) -> list[str]:
    score = _number(value)
    if score is None or not 0 <= score <= MAX_MIN_SCORE:
        return [f"Must be between 0 and {MAX_MIN_SCORE:g}"]
    return []


LAB_BOUNDS: Final[Mapping[str, Callable[[Any], list[str]]]] = {
    ck.MATCHING_DATE_WINDOW_DAYS.name: _bound_window,
    ck.MATCHING_TOLERANCES.name: _bound_tolerances,
    ck.MATCHING_BANK_FEE_BANDS.name: _bound_bands,
    ck.MATCHING_SCORER_WEIGHTS.name: _bound_weights,
    ck.MATCHING_MIN_SCORE.name: _bound_min_score,
}


def bound_errors(key: str, json_value: object) -> list[str]:
    """Hard-bound violations for one key's JSON-form value; a key without a bound is refused."""
    check = LAB_BOUNDS.get(key)
    if check is None:
        return [f"{key} has no lab bound"]
    return check(json_value)
