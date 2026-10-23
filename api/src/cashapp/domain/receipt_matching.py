"""Receipt-matching vocabulary: reservation status, who decided, and the scorer outcome."""

from enum import StrEnum


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class DecidedBy(StrEnum):
    SYSTEM = "system"
    HUMAN = "human"


class MatchOutcome(StrEnum):
    MATCHED = "matched"
    NONE = "none"
    AMBIGUOUS = "ambiguous"
    VARIANCE = "variance"
