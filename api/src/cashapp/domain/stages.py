"""Pipeline stages and work-item states. The one definition used by runners, API, UI and reports."""

from enum import StrEnum


class Stage(StrEnum):
    INTAKE = "INTAKE"
    CLASSIFY = "CLASSIFY"
    EXTRACT = "EXTRACT"
    ADJUDICATE = "ADJUDICATE"
    VALIDATE = "VALIDATE"
    RESOLVE_CUSTOMER = "RESOLVE_CUSTOMER"
    FAST_PATH = "FAST_PATH"
    MATCH_RECEIPT = "MATCH_RECEIPT"
    MATCH_LINES = "MATCH_LINES"
    APPLY = "APPLY"
    WRITE_BACK = "WRITE_BACK"
    DONE = "DONE"


PIPELINE_ORDER: tuple[Stage, ...] = (
    Stage.INTAKE,
    Stage.CLASSIFY,
    Stage.EXTRACT,
    Stage.ADJUDICATE,
    Stage.VALIDATE,
    Stage.RESOLVE_CUSTOMER,
    Stage.FAST_PATH,
    Stage.MATCH_RECEIPT,
    Stage.MATCH_LINES,
    Stage.APPLY,
    Stage.WRITE_BACK,
    Stage.DONE,
)


def next_stage(stage: Stage) -> Stage | None:
    """The stage after ``stage`` in pipeline order, or None for the last one."""
    index = PIPELINE_ORDER.index(stage)
    if index + 1 >= len(PIPELINE_ORDER):
        return None
    return PIPELINE_ORDER[index + 1]


class ItemState(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_RECEIPT = "AWAITING_RECEIPT"
    ESCALATED = "ESCALATED"
    DONE = "DONE"
    ARCHIVED = "ARCHIVED"


TERMINAL_STATES: frozenset[ItemState] = frozenset({ItemState.DONE, ItemState.ARCHIVED})
