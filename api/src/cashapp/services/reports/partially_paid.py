"""The partially paid invoices report: lines applied for less than the invoice balance."""

from datetime import date
from decimal import Decimal
from typing import Final

from cashapp.data.repositories.reports import ReportQueryRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.money import to_money
from cashapp.domain.reports import day_bounds
from cashapp.domain.status import LineStatus
from cashapp.services.reports.models import PartiallyPaidRow

PARTIALLY_PAID_STATUSES: Final[frozenset[LineStatus]] = frozenset(
    {
        LineStatus.ALLOCATION_APPLIED_SHORT_PAY,
        LineStatus.ALLOCATION_APPLIED_LESS_THAN_INSTRUCTION,
    }
)
PARTIALLY_PAID_MAX_ROWS: Final = 5000

_ZERO = Decimal("0.00")


def status_label(status: LineStatus) -> str:
    """A readable label for a line status, used when a line carries no reason of its own."""
    text = status.value.removeprefix("allocation-").replace("-", " ")
    return text[:1].upper() + text[1:]


async def partially_paid(
    uow: UnitOfWork, from_: date, to: date
) -> tuple[list[PartiallyPaidRow], bool]:
    """Rows whose short-pay line was written in ``[from_, to]`` (both days inclusive), newest first.

    The second item is True when more than ``PARTIALLY_PAID_MAX_ROWS`` rows matched.
    """
    start, _ = day_bounds(from_)
    _, end = day_bounds(to)
    # One extra row tells us whether the cap cut anything off.
    fetched = await ReportQueryRepository(uow.session).partially_paid(
        start, end, PARTIALLY_PAID_STATUSES, PARTIALLY_PAID_MAX_ROWS + 1
    )
    truncated = len(fetched) > PARTIALLY_PAID_MAX_ROWS
    rows: list[PartiallyPaidRow] = []
    for record in fetched[:PARTIALLY_PAID_MAX_ROWS]:
        line_status = record.line_status
        if line_status is None:  # the query filters on status, so this cannot happen
            continue
        original = to_money(record.balance_before if record.balance_before is not None else _ZERO)
        paid = to_money(record.applied_amount if record.applied_amount is not None else _ZERO)
        discount = to_money(record.discount_amount if record.discount_amount is not None else _ZERO)
        rows.append(
            PartiallyPaidRow(
                invoice_number=record.transaction_number or "",
                customer_account_number=record.customer_account_number,
                customer_name=record.payer_name,
                currency=record.currency or "",
                original=original,
                paid=paid,
                remaining=to_money(original - paid - discount),
                short_pay_reason=record.reason or status_label(line_status),
                line_status=line_status,
                item_id=record.work_item_id,
            )
        )
    return rows, truncated
