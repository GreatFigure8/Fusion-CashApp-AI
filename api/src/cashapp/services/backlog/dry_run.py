"""Dry-run support for the apply and write-back stations.

A dry-run item runs every stage as live traffic does (Fusion reads included) but the apply step
records what it would do and makes no Fusion write. The ledger, line-result and reservation
repositories belong to the receipt-matching and apply stories, which land in the same wave; they
are resolved by import path at call time so this module has no import-time dependency on them.
"""

import importlib
from typing import Any, Final

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.backlog import BacklogBatchRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.status import LineStatus
from cashapp.domain.work_item import SYSTEM_ACTOR_ID

DRY_RUN_KEY_PREFIX: Final = "dry-run:"
DRY_RELEASE_REASON: Final = "dry_run"


def _attr(module: str, name: str) -> Any:
    return getattr(importlib.import_module(module), name)


async def is_dry_run(uow: UnitOfWork, item: WorkItem) -> bool:
    """True when the item belongs to a batch flagged DRY_RUN. Live items cost no query."""
    if item.batch_id is None:
        return False
    batch = await uow.repo(BacklogBatchRepository).get(item.batch_id)
    return batch is not None and batch.dry_run


async def record_dry_run_line(uow: UnitOfWork, row: Any, *, clock: Clock) -> None:
    """Record what the apply step would have sent for one ledger row, and send nothing.

    The ledger row is re-keyed so the unique idempotency key stays free for a promoted real run;
    its request JSON stays as the audit of what would have been sent. The line result gets
    ``allocation-dry-run`` with the amounts the capped plan would apply. Never calls Fusion.
    """
    ledger_status = _attr("cashapp.domain.ledger", "LedgerStatus")
    ledger_repo_cls = _attr("cashapp.data.repositories.applications", "ApplicationLedgerRepository")
    line_repo_cls = _attr("cashapp.data.repositories.applications", "LineResultRepository")
    await uow.repo(ledger_repo_cls).mark(
        row,
        ledger_status.DRY_RUN,
        idempotency_key=f"{DRY_RUN_KEY_PREFIX}{row.id}",
        applied_at=clock.now(),
        applied_by=SYSTEM_ACTOR_ID,
    )
    # The residual was written by the line-matching step; it is left as it is.
    await uow.repo(line_repo_cls).upsert(
        row.work_item_id,
        row.line_no,
        line_status=LineStatus.ALLOCATION_DRY_RUN,
        applied_amount=row.amount,
        discount_amount=row.discount_amount,
    )


async def settle_dry_run_reservation(uow: UnitOfWork, item_id: int) -> None:
    """Release the receipt reservation: a dry run must never hold a receipt."""
    reservations = _attr("cashapp.data.repositories.reservations", "ReservationRepository")
    await uow.repo(reservations).release(item_id, DRY_RELEASE_REASON)
