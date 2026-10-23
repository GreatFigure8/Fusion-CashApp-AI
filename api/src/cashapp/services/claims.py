"""Claim recovery and release: put IN_PROGRESS items back on the line.

Attempts are not incremented: no stage ran to completion. Each change writes its history row and
re-emits the item's StageEvent in the same transaction.
"""

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.claims import ClaimRepository
from cashapp.data.uow import UnitOfWork, UowFactory
from cashapp.domain.clock import Clock
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.events import StageEvent, emit
from cashapp.services.history import HistoryEntry, record_history

EXPIRED_REASON = "claim expired; recovered at worker start"


class ClaimService:
    def __init__(self, uow_factory: UowFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def _return_to_pending(self, uow: UnitOfWork, item: WorkItem, reasoning: str) -> None:
        now = self._clock.now()
        stage = item.stage
        await uow.repo(ClaimRepository).update(item, state=ItemState.PENDING, claim_expires_at=None)
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.STAGE_TRANSITION,
                from_stage=stage,
                to_stage=stage,
                from_state=ItemState.IN_PROGRESS,
                to_state=ItemState.PENDING,
                reasoning=reasoning,
                at=now,
            ),
            clock=self._clock,
        )
        event = StageEvent.new(item.id, stage, clock=self._clock, attempt=item.attempts)
        await emit(uow, event, item.priority, clock=self._clock)

    async def recover_expired(self, *, batch_size: int = 100) -> int:
        """Recover every expired claim, one transaction per batch. Returns the count recovered."""
        total = 0
        while True:
            async with self._uow_factory() as uow:
                items = await uow.repo(ClaimRepository).expired_claims(
                    now=self._clock.now(), limit=batch_size
                )
                if not items:
                    return total
                for item in items:
                    await self._return_to_pending(uow, item, EXPIRED_REASON)
                await uow.commit()
                total += len(items)

    async def release(self, item_id: int, stage: Stage, *, reason: str) -> bool:
        """Return one item to PENDING if it is still IN_PROGRESS at ``stage``; else do nothing."""
        async with self._uow_factory() as uow:
            item = await uow.repo(ClaimRepository).in_progress_for_update(item_id, stage=stage)
            if item is None:
                return False
            await self._return_to_pending(uow, item, reason)
            await uow.commit()
            return True
