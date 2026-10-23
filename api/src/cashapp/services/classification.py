"""A person's override of the classify decision.

The service flushes and never commits: the row, the history entry, the transition and the
outbox event all land in the caller's one transaction.
"""

from dataclasses import dataclass

from cashapp.data.models.classification import Classification
from cashapp.data.repositories.classification import ClassificationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.classification import ClassificationOrigin
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.principal import Permission, Principal
from cashapp.domain.stages import PIPELINE_ORDER, ItemState, Stage
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.events import StageEvent, emit
from cashapp.services.actor import actor_fields
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import ItemBusy, ItemNotFound, LockConflict, is_lock_live


class InvalidClassificationState(Exception):  # noqa: N818
    def __init__(self, item_id: int, stage: Stage, state: ItemState) -> None:
        self.item_id = item_id
        self.stage = stage
        self.state = state
        super().__init__(f"Item {item_id} at {stage.value}/{state.value} is past classification")


class ClassificationForbidden(Exception):  # noqa: N818
    def __init__(self, item_id: int) -> None:
        self.item_id = item_id
        super().__init__(f"Overriding the classification of item {item_id} is not permitted")


@dataclass(frozen=True, slots=True)
class OverrideResult:
    classification: Classification
    stage: Stage
    state: ItemState
    emitted: bool


class ClassificationOverrideService:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock: Clock = clock or SystemClock()

    async def override(
        self,
        uow: UnitOfWork,
        item_id: int,
        principal: Principal,
        *,
        is_remittance: bool,
        reason: str,
    ) -> OverrideResult:
        if not principal.can(Permission.CLASSIFICATION_OVERRIDE):
            raise ClassificationForbidden(item_id)
        cleaned = reason.strip()
        if not cleaned:
            raise ValueError("A reason is required to override a classification")

        item = await uow.work_items.get_for_update(item_id, skip_locked=False)
        if item is None:
            raise ItemNotFound(item_id)
        now = self._clock.now()
        if is_lock_live(item, now) and item.lock_owner != principal.subject:
            raise LockConflict(
                item_id,
                item.lock_owner_name or item.lock_owner or "",
                item.lock_acquired_at or now,
            )
        if (
            item.state == ItemState.IN_PROGRESS
            and item.claim_expires_at is not None
            and item.claim_expires_at > now
        ):
            raise ItemBusy(item_id)
        if PIPELINE_ORDER.index(item.stage) > PIPELINE_ORDER.index(Stage.EXTRACT):
            raise InvalidClassificationState(item_id, item.stage, item.state)

        row = await uow.repo(ClassificationRepository).add(
            Classification(
                work_item_id=item_id,
                is_remittance=is_remittance,
                reason=cleaned,
                confidence=None,
                model_id=None,
                prompt_version=None,
                origin=ClassificationOrigin.HUMAN,
                decided_by=principal.subject,
                created_at=now,
            )
        )

        from_stage, from_state = item.stage, item.state
        emitted = False
        archived = item.state == ItemState.ARCHIVED
        if is_remittance:
            if item.stage == Stage.CLASSIFY or archived:
                await uow.work_items.update(
                    item,
                    stage=Stage.EXTRACT,
                    state=ItemState.PENDING,
                    attempts=0,
                    last_error_code=None,
                    last_error_detail=None,
                    claim_expires_at=None,
                    updated_at=now,
                )
                await emit(
                    uow,
                    StageEvent.new(item.id, Stage.EXTRACT, clock=self._clock),
                    item.priority,
                    clock=self._clock,
                )
                emitted = True
        elif not archived:
            await uow.work_items.update(
                item, state=ItemState.ARCHIVED, claim_expires_at=None, updated_at=now
            )

        await record_history(
            uow,
            item_id,
            HistoryEntry(
                action=HistoryAction.HUMAN_ACTION,
                **actor_fields(principal),
                from_stage=from_stage,
                to_stage=item.stage,
                from_state=from_state,
                to_state=item.state,
                reasoning=cleaned,
                payload={
                    "event": "classification_override",
                    "is_remittance": is_remittance,
                    "classification_id": row.id,
                },
            ),
            clock=self._clock,
        )
        return OverrideResult(
            classification=row, stage=item.stage, state=item.state, emitted=emitted
        )
