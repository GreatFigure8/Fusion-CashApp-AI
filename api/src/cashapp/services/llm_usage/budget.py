"""The daily LLM spend budget: one ``budget_exceeded`` notification per UTC day, across processes.

The alert row's primary key (the day) is what makes it once per day; the caller catches the
``IntegrityError`` a second writer gets. The alert row and its outbox message commit together.
The event carries totals only: no prompt, artifact or payer text.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Final

from cashapp.data.models.llm_usage import LlmBudgetAlert
from cashapp.data.repositories.llm_usage import LlmBudgetAlertRepository, LlmUsageRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.notifications import NotifyEvent, NotifyKind, NotifySeverity
from cashapp.services.notify import emit_notify

__all__ = ["BUDGET_NOTIFY_KIND", "check_budget"]

BUDGET_NOTIFY_KIND: Final = NotifyKind.BUDGET_EXCEEDED


async def check_budget(
    uow: UnitOfWork, *, day: date, limit: Decimal, now: datetime
) -> NotifyEvent | None:
    """Emit the day's budget alert when spend is over ``limit`` and none was emitted yet.

    Returns the event, or ``None`` when the day is within budget. Raises ``IntegrityError`` on
    the flush when another process already alerted today. The caller owns the commit.
    """
    total = await uow.repo(LlmUsageRepository).cost_for_day(day)
    if total <= limit:
        return None
    await uow.repo(LlmBudgetAlertRepository).add(
        LlmBudgetAlert(alert_day=day, limit_usd=limit, total_usd=total, emitted_at=now)
    )
    event = NotifyEvent(
        kind=BUDGET_NOTIFY_KIND,
        severity=NotifySeverity.WARNING,
        summary=(
            f"LLM spend for {day.isoformat()} UTC is {total} USD, "
            f"over the daily budget of {limit} USD"
        ),
        occurred_at=now,
    )
    await emit_notify(uow, event)
    return event
