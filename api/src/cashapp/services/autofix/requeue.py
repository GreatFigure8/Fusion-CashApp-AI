"""Human requeue: a person fixes the data and sends the item back down the same assembly line.

There is no manual code path. Requeue puts the item PENDING at a stage and emits that stage's
event; the ordinary ``StageRunner`` picks it up. Everything happens in the caller's single
transaction (flush, never commit): the correction, the hints, the alias, the lock release, the
history row and the event.

Services that land in the same wave (s09 corrections, s37 aliases) are loaded at call time, so
this module imports cleanly whichever order they merge in.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cashapp.data.models.work_item import WorkItem
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.extraction import RemittanceExtraction
from cashapp.domain.principal import Principal
from cashapp.domain.stages import PIPELINE_ORDER, TERMINAL_STATES, ItemState, Stage
from cashapp.domain.work_item import HistoryAction, HumanHints
from cashapp.pipeline.events import StageEvent, emit
from cashapp.pipeline.health import CONSUMED_STAGES
from cashapp.services.actor import actor_fields
from cashapp.services.autofix.diff import FieldChange, extraction_diff
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import ItemNotFound, LockService

_CORRECTION_FLOOR = Stage.VALIDATE


@dataclass(frozen=True, slots=True)
class RequeueCommand:
    note: str
    target_stage: Stage | None = None
    corrected_extraction: RemittanceExtraction | None = None
    customer_number: str | None = None
    receipt_id: int | None = None
    learn_alias: bool = True


@dataclass(frozen=True, slots=True)
class RequeueResult:
    item_id: int
    stage: Stage
    state: ItemState
    changes: tuple[FieldChange, ...]
    alias_id: int | None


class RequeueError(Exception):
    def __init__(self, item_id: int, message: str | None = None) -> None:
        self.item_id = item_id
        super().__init__(message or f"{type(self).__name__} for item {item_id}")


class ItemNotRequeueable(RequeueError):  # noqa: N818
    def __init__(self, item_id: int, state: ItemState) -> None:
        self.state = state
        super().__init__(item_id, f"Item {item_id} is {state.value} and cannot be requeued")


class InvalidTargetStage(RequeueError):  # noqa: N818
    def __init__(self, item_id: int, target_stage: str, reason: str) -> None:
        self.target_stage = target_stage
        self.reason = reason
        super().__init__(item_id, f"Cannot requeue item {item_id} at {target_stage}: {reason}")


AliasFactory = Callable[[UnitOfWork], Any]


def _default_alias_factory(clock: Clock) -> AliasFactory:
    def build(uow: UnitOfWork) -> Any:
        service = getattr(importlib.import_module("cashapp.services.aliases"), "AliasService")  # noqa: B009
        return service(uow, clock=clock)

    return build


def _load(module: str, name: str) -> Any:
    return getattr(importlib.import_module(module), name)


def _extraction_of(adjudication: Any) -> RemittanceExtraction | None:
    """The final extraction of an adjudication row, or None when absent or purged."""
    if adjudication is None:
        return None
    try:
        final = adjudication.result().final
    except Exception:  # a purged payload has nothing to diff against
        return None
    return final if isinstance(final, RemittanceExtraction) else None


class RequeueService:
    def __init__(
        self,
        *,
        lock_service: LockService,
        alias_service: AliasFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._locks = lock_service
        self._clock: Clock = clock or SystemClock()
        self._alias_factory: AliasFactory = alias_service or _default_alias_factory(self._clock)

    @staticmethod
    def _choose_target(item: WorkItem, cmd: RequeueCommand) -> Stage:
        corrected = cmd.corrected_extraction is not None
        target = cmd.target_stage
        if target is None:
            target = _CORRECTION_FLOOR if corrected else item.stage
        if target not in CONSUMED_STAGES:
            raise InvalidTargetStage(item.id, target.value, "That stage has no consumer")
        if corrected and PIPELINE_ORDER.index(target) < PIPELINE_ORDER.index(_CORRECTION_FLOOR):
            raise InvalidTargetStage(
                item.id,
                target.value,
                f"A corrected extraction must go to {_CORRECTION_FLOOR.value} or later",
            )
        return target

    async def requeue(
        self, uow: UnitOfWork, item_id: int, cmd: RequeueCommand, principal: Principal
    ) -> RequeueResult:
        now = self._clock.now()
        item = await uow.work_items.get_for_update(item_id, skip_locked=False)
        if item is None:
            raise ItemNotFound(item_id)
        self._locks.assert_held_by(item, principal, now)
        if item.state in TERMINAL_STATES:
            raise ItemNotRequeueable(item_id, item.state)
        target = self._choose_target(item, cmd)
        from_stage, from_state = item.stage, item.state

        repo = _load("cashapp.data.repositories.adjudication", "AdjudicationRepository")
        latest = await uow.repo(repo).latest_for(item_id)
        before = _extraction_of(latest)
        changes: list[FieldChange] = []
        current = before
        if cmd.corrected_extraction is not None:
            save = _load("cashapp.services.adjudication", "save_human_correction")
            await save(uow, item_id, cmd.corrected_extraction, principal, clock=self._clock)
            changes = extraction_diff(before, cmd.corrected_extraction)
            current = cmd.corrected_extraction

        hints = HumanHints(target_stage=target.value)
        if cmd.customer_number is not None:
            hints["customer_number"] = cmd.customer_number
        if cmd.receipt_id is not None:
            hints["receipt_id"] = cmd.receipt_id
        await uow.work_items.update(
            item,
            human_hints=hints,
            fix_hints=None,
            attempts=0,
            last_error_code=None,
            last_error_detail=None,
            escalation_summary=None,
            awaiting_since=None,
            stage=target,
            state=ItemState.PENDING,
            claim_expires_at=None,
        )

        alias_id: int | None = None
        if cmd.customer_number is not None and cmd.learn_alias:
            payer = current.payer_name.value if current is not None else None
            bank = current.payer_bank_account.value if current is not None else None
            learned = await self._alias_factory(uow).learn(
                uow,
                item_id=item_id,
                payer_name=payer or item.payer_name,
                bank_account=bank,
                reference_pattern=None,
                customer_number=cmd.customer_number,
                principal=principal,
            )
            aliases = getattr(learned, "aliases", ())
            alias_id = aliases[0].id if aliases else None

        await self._locks.release(uow, item_id, principal, redrive=False)

        await record_history(
            uow,
            item_id,
            HistoryEntry(
                action=HistoryAction.HUMAN_ACTION,
                **actor_fields(principal),
                from_stage=from_stage,
                to_stage=target,
                from_state=from_state,
                to_state=ItemState.PENDING,
                reasoning=cmd.note,
                payload={
                    "event": "requeue",
                    "target_stage": target.value,
                    "changes": [
                        {"path": c.path, "before": c.before, "after": c.after} for c in changes
                    ],
                    "customer_number": cmd.customer_number,
                    "receipt_id": cmd.receipt_id,
                    "learn_alias": cmd.learn_alias,
                    "alias_id": alias_id,
                },
            ),
            clock=self._clock,
        )
        await emit(
            uow,
            StageEvent.new(item_id, target, clock=self._clock),
            item.priority,
            clock=self._clock,
        )
        return RequeueResult(
            item_id=item_id,
            stage=target,
            state=ItemState.PENDING,
            changes=tuple(changes),
            alias_id=alias_id,
        )
