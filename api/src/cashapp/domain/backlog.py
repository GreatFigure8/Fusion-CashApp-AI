"""Backlog batch vocabulary: statuses, the transition table, counts and the ETA rule. Pure."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from cashapp.domain.stages import PIPELINE_ORDER, Stage


class BacklogStatus(StrEnum):
    IMPORTING = "IMPORTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class BacklogSourceKind(StrEnum):
    FOLDER = "FOLDER"
    MAILBOX_FOLDER = "MAILBOX_FOLDER"


TERMINAL_BATCH_STATUSES: Final[frozenset[BacklogStatus]] = frozenset(
    {BacklogStatus.DONE, BacklogStatus.CANCELLED}
)

# (status, action) -> new status. ``imported`` and ``complete`` are system actions.
ALLOWED_TRANSITIONS: Final[Mapping[tuple[BacklogStatus, str], BacklogStatus]] = MappingProxyType(
    {
        (BacklogStatus.IMPORTING, "pause"): BacklogStatus.PAUSED,
        (BacklogStatus.IMPORTING, "imported"): BacklogStatus.RUNNING,
        (BacklogStatus.IMPORTING, "cancel"): BacklogStatus.CANCELLED,
        (BacklogStatus.RUNNING, "pause"): BacklogStatus.PAUSED,
        (BacklogStatus.RUNNING, "complete"): BacklogStatus.DONE,
        (BacklogStatus.RUNNING, "cancel"): BacklogStatus.CANCELLED,
        (BacklogStatus.PAUSED, "resume"): BacklogStatus.RUNNING,
        (BacklogStatus.PAUSED, "cancel"): BacklogStatus.CANCELLED,
    }
)

BATCH_NAME_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
_NAME_RE: Final = re.compile(BATCH_NAME_PATTERN)

# Each stage hop is one throttled outbox row: every stage after INTAKE up to, not including, DONE.
CONSUMED_STAGES: Final[tuple[Stage, ...]] = tuple(
    stage for stage in PIPELINE_ORDER if stage not in {Stage.INTAKE, Stage.DONE}
)


def validate_batch_name(name: str) -> str:
    """The name unchanged when it matches ``BATCH_NAME_PATTERN``; ValueError otherwise."""
    if _NAME_RE.fullmatch(name) is None:
        raise ValueError(f"batch name must match {BATCH_NAME_PATTERN}")
    return name


@dataclass(frozen=True, slots=True)
class BatchCounts:
    items: int
    processed: int
    applied: int
    escalated: int
    failed: int
    awaiting: int
    in_flight: int


@dataclass(frozen=True, slots=True)
class BatchProgress:
    """What the API and the flow monitor render for one batch."""

    id: int
    name: str
    status: BacklogStatus
    dry_run: bool
    source_kind: BacklogSourceKind
    total: int
    processed: int
    applied: int
    escalated: int
    failed: int
    awaiting: int
    in_flight: int
    rate_limit_per_minute: int
    eta_minutes: int | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: str
    promoted_from_id: int | None
    import_error: str | None


def estimate_eta_minutes(
    counts: BatchCounts,
    *,
    status: BacklogStatus,
    rate_per_min: int,
    started_at: datetime | None,
    now: datetime,
) -> int | None:
    """Minutes left, or None when no estimate is meaningful (paused, cancelled, nothing yet)."""
    if status in {BacklogStatus.PAUSED, BacklogStatus.CANCELLED}:
        return None
    if status == BacklogStatus.DONE:
        return 0
    if status == BacklogStatus.IMPORTING and counts.items == 0:
        return None
    if counts.in_flight == 0:
        return 0
    if started_at is not None and counts.processed > 0:
        elapsed_min = (now - started_at).total_seconds() / 60
        if elapsed_min >= 1:
            return math.ceil(counts.in_flight * elapsed_min / counts.processed)
    return math.ceil(counts.in_flight * len(CONSUMED_STAGES) / max(rate_per_min, 1))
