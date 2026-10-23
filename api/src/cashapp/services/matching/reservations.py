"""Reserve a receipt for a work item so two remittances never take the same one."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from cashapp.data.models.receipt_matching import ReceiptReservation
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.reservations import ReservationConflict, ReservationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.stages import ItemState
from cashapp.domain.work_item import HistoryAction
from cashapp.pipeline.errors import StageError
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import is_locked_for_automation

# A holder in one of these states is not going to use the receipt (unless a person is working it).
STALE_HOLDER_STATES: Final[frozenset[ItemState]] = frozenset(
    {ItemState.ESCALATED, ItemState.ARCHIVED}
)


@dataclass(frozen=True, slots=True)
class ReservationClaim:
    reservation: ReceiptReservation
    released_own_receipt_id: int | None
    released_stale_holder_item_id: int | None


class ReservationService:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def _note(
        self, uow: UnitOfWork, item_id: int, reasoning: str, payload: dict[str, object]
    ) -> None:
        await record_history(
            uow,
            item_id,
            HistoryEntry(action=HistoryAction.DECISION, reasoning=reasoning, payload=payload),
            clock=self._clock,
        )

    def _is_stale(self, holder: WorkItem | None, now: datetime) -> bool:
        if holder is None:
            return True  # the holder item no longer exists
        return holder.state in STALE_HOLDER_STATES and not is_locked_for_automation(holder, now)

    async def claim(
        self,
        uow: UnitOfWork,
        *,
        item: WorkItem,
        receipt_id: int,
        receipt_number: str | None,
        now: datetime,
    ) -> ReservationClaim:
        """Make ``receipt_id`` this item's one ACTIVE reservation, or raise RECEIPT_RESERVED."""
        repo = uow.repo(ReservationRepository)
        label = receipt_number or str(receipt_id)

        released_own: int | None = None
        own = await repo.active_for_item(item.id)
        if own is not None:
            if own.receipt_id == receipt_id:
                return ReservationClaim(own, None, None)
            released_own = own.receipt_id
            await repo.release(item.id, f"rematched to receipt {label}", now=now)
            await self._note(
                uow,
                item.id,
                f"Released the earlier reservation on receipt "
                f"{own.receipt_number or own.receipt_id} because the item matched receipt {label}",
                {"released_receipt_id": own.receipt_id, "new_receipt_id": receipt_id},
            )

        released_holder: int | None = None
        holder = await repo.active_for_receipt(receipt_id)
        if holder is not None and holder.work_item_id != item.id:
            holder_item = await uow.work_items.get(holder.work_item_id)
            if not self._is_stale(holder_item, now):
                raise StageError(
                    ErrorCode.RECEIPT_RESERVED,
                    {"receipt_id": receipt_id, "holder_item_id": holder.work_item_id},
                )
            await repo.release_row(
                holder,
                f"released: holder item {holder.work_item_id} is no longer working it",
                now=now,
            )
            released_holder = holder.work_item_id
            payload: dict[str, object] = {
                "receipt_id": receipt_id,
                "holder_item_id": holder.work_item_id,
                "new_holder_item_id": item.id,
            }
            await self._note(
                uow,
                item.id,
                f"Took over receipt {label} from item {holder.work_item_id}, which is escalated "
                "or archived and not being worked",
                payload,
            )
            if holder_item is not None:
                await self._note(
                    uow,
                    holder_item.id,
                    f"Receipt {label} was released to item {item.id} because this item is "
                    "escalated or archived and not being worked",
                    payload,
                )

        try:
            row = await repo.reserve(receipt_id, item.id, receipt_number=receipt_number, now=now)
        except ReservationConflict as exc:
            raise StageError(
                ErrorCode.RECEIPT_RESERVED, {"receipt_id": receipt_id, "contended": True}
            ) from exc
        return ReservationClaim(row, released_own, released_holder)
