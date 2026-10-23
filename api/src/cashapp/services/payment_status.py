"""The one place that turns the ledger and line results into a header and calls ``roll_up``."""

from decimal import Decimal

from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.uow import UnitOfWork
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.status import HeaderResult, LineStatus, PaymentStatus, roll_up


async def derive_payment_status(uow: UnitOfWork, item: WorkItem) -> PaymentStatus:
    """Re-derive the payment status strictly from the item's ledger and line results."""
    ledger_rows = await uow.repo(ApplicationLedgerRepository).for_item(item.id)
    line_rows = await uow.repo(LineResultRepository).for_item(item.id)
    applied_total = sum(
        (row.amount for row in ledger_rows if row.status is LedgerStatus.APPLIED), Decimal("0")
    )
    header = HeaderResult(
        customer_found=item.customer_account_number is not None,
        payment_date_present=item.payment_date is not None,
        receipt_found=len(ledger_rows) > 0,
        applied_total=applied_total,
        total_due=item.payment_amount if item.payment_amount is not None else Decimal("0"),
        receipt_closed=False,
        dry_run=False,
    )
    statuses: list[LineStatus] = [r.line_status for r in line_rows if r.line_status is not None]
    return roll_up(header, statuses)
