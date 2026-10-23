"""Work-item vocabulary shared by the data layer, runners, services and API."""

from enum import StrEnum
from typing import Literal, TypedDict


class SourceKind(StrEnum):
    MAILBOX = "MAILBOX"
    FOLDER = "FOLDER"
    BACKLOG = "BACKLOG"
    MANUAL = "MANUAL"


class ActorKind(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"


class HistoryAction(StrEnum):
    STAGE_TRANSITION = "STAGE_TRANSITION"
    AUTOFIX_ATTEMPT = "AUTOFIX_ATTEMPT"
    HUMAN_ACTION = "HUMAN_ACTION"
    FUSION_WRITE = "FUSION_WRITE"
    DECISION = "DECISION"
    LOCK = "LOCK"


SYSTEM_ACTOR_ID = "system"
SYSTEM_ACTOR_NAME = "CashApp automation"

PRIORITY_LIVE = 100
PRIORITY_BACKLOG = 10


class HumanHints(TypedDict, total=False):
    """Written only by a human requeue (s18)."""

    customer_number: str
    receipt_id: int
    target_stage: str


class FixHints(TypedDict, total=False):
    """Written only by auto-fix handlers (s18)."""

    rerun_readers: list[Literal["A", "B"]]
    effort: str
    gl_date_floor: str
    widen_window_days: int
    match_on_creation_date: bool
