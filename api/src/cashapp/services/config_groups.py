"""Frozen, typed views over the registry's flat config keys, one model per group.

Mapping fields are read-only proxies over private copies and sequences are tuples, so a
station can hold a group for the length of one event without it changing underneath.
"""

import copy
import datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from cashapp.domain.config_keys import BankFeeBand
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import Stage

__all__ = [
    "AgingConfig",
    "BacklogConfig",
    "BankFeeBand",
    "BudgetConfig",
    "ConcurrencyConfig",
    "DiscountConfig",
    "EscalationConfig",
    "ExtractionConfig",
    "IntakeConfig",
    "LocksConfig",
    "MatchingConfig",
    "ModelRole",
    "ModelsConfig",
    "NotificationsConfig",
    "ReceiptWatcherConfig",
    "ReportsConfig",
    "RetentionConfig",
    "RetriesConfig",
]

WILDCARD = "*"


def _freeze[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    return MappingProxyType(copy.deepcopy(dict(mapping)))


@dataclass(frozen=True, slots=True)
class ModelRole:
    model_id: str
    effort: str | None
    timeout_s: float


@dataclass(frozen=True, slots=True)
class IntakeConfig:
    poll_interval_seconds: int


@dataclass(frozen=True, slots=True)
class ReceiptWatcherConfig:
    poll_interval_seconds: int


@dataclass(frozen=True, slots=True)
class MatchingConfig:
    date_window_days: int
    tolerances: Mapping[str, Decimal]
    bank_fee_bands: tuple[BankFeeBand, ...]
    scorer_weights: Mapping[str, float]
    min_score: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "tolerances", _freeze(self.tolerances))
        object.__setattr__(self, "scorer_weights", _freeze(self.scorer_weights))

    def tolerance_for(self, currency: str) -> Decimal:
        """Tolerance for `currency` (case-insensitive), else the "*" fallback."""
        found = self.tolerances.get(currency.upper())
        return found if found is not None else self.tolerances[WILDCARD]


@dataclass(frozen=True, slots=True)
class RetriesConfig:
    max_attempts: Mapping[str, int]
    backoff_seconds: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_attempts", _freeze(self.max_attempts))

    def max_attempts_for(self, code: ErrorCode) -> int:
        found = self.max_attempts.get(code.value)
        return found if found is not None else self.max_attempts[WILDCARD]

    def backoff_for(self, attempt: int) -> int:
        """Delay before retry number `attempt` (1-based); clamps to the last entry."""
        index = min(max(attempt, 1), len(self.backoff_seconds)) - 1
        return self.backoff_seconds[index]


@dataclass(frozen=True, slots=True)
class AgingConfig:
    awaiting_receipt_max_days: int


@dataclass(frozen=True, slots=True)
class EscalationConfig:
    min_extraction_confidence: float


@dataclass(frozen=True, slots=True)
class ModelsConfig:
    reader_a: ModelRole
    reader_b: ModelRole
    adjudicator: ModelRole
    workhorse: ModelRole


@dataclass(frozen=True, slots=True)
class ExtractionConfig:
    fanin_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class ConcurrencyConfig:
    per_stage: Mapping[str, int]
    apply_per_receipt: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "per_stage", _freeze(self.per_stage))

    def for_stage(self, stage: Stage) -> int:
        found = self.per_stage.get(stage.value)
        return found if found is not None else self.per_stage[WILDCARD]


@dataclass(frozen=True, slots=True)
class LocksConfig:
    lease_minutes: int


@dataclass(frozen=True, slots=True)
class BacklogConfig:
    rate_limit_per_minute: int


@dataclass(frozen=True, slots=True)
class RetentionConfig:
    raw_artifact_days: int | None
    extraction_days: int | None
    history_payload_days: int | None


@dataclass(frozen=True, slots=True)
class BudgetConfig:
    daily_usd: Decimal | None


@dataclass(frozen=True, slots=True)
class NotificationsConfig:
    """`recipients` maps notification kind -> channel ("email" or "webhook") -> addresses."""

    recipients: Mapping[str, Mapping[str, tuple[str, ...]]]
    batch_window_seconds: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "recipients",
            MappingProxyType(
                {kind: _freeze(channels) for kind, channels in self.recipients.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class ReportsConfig:
    daily_summary_cutover: datetime.time


@dataclass(frozen=True, slots=True)
class DiscountConfig:
    enabled: bool
