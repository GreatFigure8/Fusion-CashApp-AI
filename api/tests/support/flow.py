"""Seed data for the flow monitor tests: items at several stages, transitions and ledger rows."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cashapp.data.models.applications import ApplicationLedger
from cashapp.data.models.work_item import WorkItem, WorkItemHistory
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.domain.work_item import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME, ActorKind, HistoryAction
from tests.support.factories import make_work_item


@dataclass
class SeededFlow:
    envelope_id: int
    child_id: int
    auto_applied_id: int
    human_applied_id: int
    escalated_id: int
    errored_id: int
    yesterday_id: int
    awaiting_ids: dict[str, int] = field(default_factory=lambda: {})


async def _item(uow: UnitOfWork, at: datetime, **fields: Any) -> WorkItem:
    return await uow.work_items.add(make_work_item(created_at=at, updated_at=at, **fields))


async def transition(
    uow: UnitOfWork,
    item: WorkItem,
    at: datetime,
    *,
    from_stage: Stage,
    to_stage: Stage,
    to_state: ItemState = ItemState.PENDING,
    action: HistoryAction = HistoryAction.STAGE_TRANSITION,
) -> None:
    uow.session.add(
        WorkItemHistory(
            work_item_id=item.id,
            at=at,
            actor_kind=ActorKind.SYSTEM,
            actor_id=SYSTEM_ACTOR_ID,
            actor_name=SYSTEM_ACTOR_NAME,
            action=action,
            from_stage=from_stage,
            to_stage=to_stage,
            from_state=ItemState.IN_PROGRESS,
            to_state=to_state,
        )
    )
    await uow.session.flush()


async def seed_flow(uow: UnitOfWork, clock: Clock, *, with_ledger: bool = True) -> SeededFlow:
    """One day of activity around ``clock.now()`` (expects a mid-day clock)."""
    now = clock.now()
    today = now - timedelta(hours=2)
    yesterday = now - timedelta(days=1, hours=2)

    envelope = await _item(uow, today, stage=Stage.DONE, state=ItemState.DONE)
    child = await _item(
        uow, today, stage=Stage.CLASSIFY, state=ItemState.PENDING, parent_id=envelope.id
    )
    auto = await _item(
        uow,
        today,
        stage=Stage.DONE,
        state=ItemState.DONE,
        payment_status=PaymentStatus.PAYMENT_SUCCESS,
        currency="USD",
        payment_amount=Decimal("100.00"),
    )
    human = await _item(
        uow,
        today,
        stage=Stage.DONE,
        state=ItemState.DONE,
        payment_status=PaymentStatus.PAYMENT_SUCCESS,
        currency="USD",
        payment_amount=Decimal("50.00"),
    )
    await transition(
        uow,
        human,
        today,
        from_stage=Stage.MATCH_LINES,
        to_stage=Stage.MATCH_LINES,
        action=HistoryAction.HUMAN_ACTION,
    )
    escalated = await _item(uow, today, stage=Stage.MATCH_RECEIPT, state=ItemState.ESCALATED)
    errored = await _item(uow, today, stage=Stage.EXTRACT, state=ItemState.PENDING, attempts=1)
    yesterday_item = await _item(uow, yesterday, stage=Stage.CLASSIFY, state=ItemState.PENDING)

    awaiting: dict[str, int] = {}
    for label, days in (("0-2d", 1), ("3-7d", 5), ("8-30d", 20), (">30d", 40)):
        waiting = await _item(
            uow,
            now - timedelta(days=days),
            stage=Stage.MATCH_RECEIPT,
            state=ItemState.AWAITING_RECEIPT,
            awaiting_since=now - timedelta(days=days),
        )
        awaiting[label] = waiting.id

    if with_ledger:
        for item, amount in ((auto, "100.00"), (human, "50.00")):
            row: dict[str, Any] = {
                "work_item_id": item.id,
                "line_no": 1,
                "receipt_id": 1,
                "customer_trx_id": 1,
                "apply_seq": 1,
                "amount": Decimal(amount),
                "idempotency_key": f"{item.id}:1:1",
                "status": LedgerStatus.APPLIED,
                "applied_at": today,
            }
            uow.session.add(ApplicationLedger(**row))
        await uow.session.flush()

    return SeededFlow(
        envelope_id=envelope.id,
        child_id=child.id,
        auto_applied_id=auto.id,
        human_applied_id=human.id,
        escalated_id=escalated.id,
        errored_id=errored.id,
        yesterday_id=yesterday_item.id,
        awaiting_ids=awaiting,
    )
