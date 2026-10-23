"""Per-work-item logging context, carried in contextvars so concurrent tasks never leak."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from cashapp.domain.stages import Stage

_work_item_id: ContextVar[int | None] = ContextVar("obs_work_item_id", default=None)
_stage: ContextVar[str | None] = ContextVar("obs_stage", default=None)
_attempt: ContextVar[int | None] = ContextVar("obs_attempt", default=None)
_trace_id: ContextVar[str | None] = ContextVar("obs_trace_id", default=None)


@dataclass(frozen=True, slots=True)
class ItemContext:
    work_item_id: int | None
    stage: str | None
    attempt: int | None
    trace_id: str | None


def current_item_context() -> ItemContext:
    return ItemContext(
        work_item_id=_work_item_id.get(),
        stage=_stage.get(),
        attempt=_attempt.get(),
        trace_id=_trace_id.get(),
    )


@contextmanager
def bind_item_context(
    work_item_id: int, stage: Stage | str, attempt: int, trace_id: str | None = None
) -> Generator[ItemContext]:
    """Bind the item being processed; the previous binding is restored on exit."""
    stage_name = stage.value if isinstance(stage, Stage) else stage
    tokens = (
        _work_item_id.set(work_item_id),
        _stage.set(stage_name),
        _attempt.set(attempt),
        _trace_id.set(trace_id),
    )
    try:
        yield current_item_context()
    finally:
        _work_item_id.reset(tokens[0])
        _stage.reset(tokens[1])
        _attempt.reset(tokens[2])
        _trace_id.reset(tokens[3])
