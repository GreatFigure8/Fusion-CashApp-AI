"""Rules for items parked in AWAITING_RECEIPT: wake them on a matching receipt, or age them out.

Nothing here commits. The caller (the consumer or the watcher) owns the transaction, so a wake, its
history row and its stage event land together or not at all.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.awaiting import AwaitingReceiptRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.receipt_arrived import ReceiptArrived
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.events import StageEvent, emit
from cashapp.services.autofix.escalation import escalate
from cashapp.services.config_groups import MatchingConfig
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import is_locked_for_automation

WOKEN_REASONING_PREFIX: Final = "woken by receipt "


@dataclass(frozen=True, slots=True)
class WakeResult:
    receipt_id: int
    woken_ids: tuple[int, ...]


async def wake_for_receipt(
    uow: UnitOfWork, event: ReceiptArrived, *, matching: MatchingConfig, clock: Clock
) -> WakeResult:
    """Move every awaiting item the receipt could match back to MATCH_RECEIPT. Never commits."""
    now = clock.now()
    items = await uow.repo(AwaitingReceiptRepository).candidates_for(
        event,
        matching.date_window_days,
        matching.tolerance_for(event.currency),
        now=now,
    )
    woken: list[int] = []
    for item in items:
        if item.state != ItemState.AWAITING_RECEIPT or is_locked_for_automation(item, now):
            continue
        from_stage = item.stage
        item.stage = Stage.MATCH_RECEIPT
        item.state = ItemState.PENDING
        item.attempts = 0
        item.claim_expires_at = None
        item.last_error_code = None
        item.last_error_detail = None
        # awaiting_since (aging spans re-parks) and fix_hints (s18's creation-date hint) are kept.
        await uow.work_items.update(item, updated_at=now)
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.STAGE_TRANSITION,
                from_stage=from_stage,
                to_stage=Stage.MATCH_RECEIPT,
                from_state=ItemState.AWAITING_RECEIPT,
                to_state=ItemState.PENDING,
                reasoning=f"{WOKEN_REASONING_PREFIX}{event.receipt_number}",
                payload={
                    "receipt_id": event.receipt_id,
                    "receipt_number": event.receipt_number,
                    "event_id": str(event.event_id),
                    "currency": event.currency,
                    "unapplied_amount": event.unapplied_amount,
                    "customer_account_number": event.customer_account_number,
                },
            ),
            clock=clock,
        )
        await emit(
            uow,
            StageEvent.new(item.id, Stage.MATCH_RECEIPT, clock=clock),
            priority=item.priority,
            clock=clock,
        )
        woken.append(item.id)
    return WakeResult(receipt_id=event.receipt_id, woken_ids=tuple(woken))


def aged_out_summary(item: WorkItem, max_days: int, now: datetime) -> str:
    """A fixed template: no LLM and no remittance content."""
    since = item.awaiting_since if item.awaiting_since is not None else now
    return (
        f"No matching Fusion receipt appeared within {max_days} days "
        f"(awaiting since {since:%Y-%m-%d})."
    )


async def escalate_aged(
    uow: UnitOfWork, items: Sequence[WorkItem], *, max_days: int, clock: Clock
) -> list[int]:
    """Escalate each aged-out item to a person (AGED_OUT). Never commits."""
    now = clock.now()
    escalated: list[int] = []
    for item in items:
        await escalate(
            uow,
            item,
            ErrorCode.AGED_OUT,
            aged_out_summary(item, max_days, now),
            clock=clock,
        )
        escalated.append(item.id)
    return escalated
