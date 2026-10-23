"""Hand an item to a person, outside the stage runner's own failure path (s14, s38, s42 sources).

The caller passes an item it has already locked (``FOR UPDATE``). Nothing here commits.
"""

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.notifications import NotifyEvent, NotifyKind, NotifySeverity
from cashapp.domain.principal import SYSTEM_PRINCIPAL, Principal
from cashapp.domain.stages import ItemState
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.errors import StageError
from cashapp.services.actor import actor_fields
from cashapp.services.autofix.attempts import load_attempts
from cashapp.services.autofix.reasoner import template_summary
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.notify import emit_notify


async def announce_escalation(
    uow: UnitOfWork,
    item: WorkItem,
    code: ErrorCode,
    summary: str,
    *,
    clock: Clock | None = None,
) -> NotifyEvent:
    """Emit the ``item_escalated`` notification (WARNING; never CRITICAL for a single item)."""
    the_clock = clock or SystemClock()
    event = NotifyEvent.new(
        NotifyKind.ITEM_ESCALATED,
        NotifySeverity.WARNING,
        summary.strip() or code.spec.description,
        clock=the_clock,
        work_item_id=item.id,
        error_code=code,
    )
    await emit_notify(uow, event, clock=the_clock)
    return event


async def escalate(
    uow: UnitOfWork,
    item: WorkItem,
    code: ErrorCode,
    summary: str | None,
    principal: Principal = SYSTEM_PRINCIPAL,
    *,
    clock: Clock | None = None,
) -> None:
    """Set ESCALATED with the code and a summary, write the history row and notify."""
    the_clock = clock or SystemClock()
    text = summary
    if text is None:
        attempts = await load_attempts(uow, item.id)
        text = template_summary(item, StageError(code), attempts)
    from_state = item.state
    await uow.work_items.update(
        item,
        state=ItemState.ESCALATED,
        last_error_code=code,
        escalation_summary=text,
        claim_expires_at=None,
    )
    await record_history(
        uow,
        item.id,
        HistoryEntry(
            action=HistoryAction.STAGE_TRANSITION,
            **actor_fields(principal),
            from_stage=item.stage,
            to_stage=item.stage,
            from_state=from_state,
            to_state=ItemState.ESCALATED,
            error_code=code,
            reasoning=text,
            payload={"decision": "escalate"},
        ),
        clock=the_clock,
    )
    await announce_escalation(uow, item, code, text, clock=the_clock)
