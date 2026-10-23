"""Queries over LLM_USAGE and LLM_BUDGET_ALERT. Flushes, never commits."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import case, delete, func, select
from sqlalchemy.engine import CursorResult

from cashapp.data.models.llm_usage import LlmBudgetAlert, LlmUsage
from cashapp.data.repository import BaseRepository
from cashapp.domain.llm_usage import LlmRole, UsageGroupBy


@dataclass(frozen=True, slots=True)
class DailyUsageRow:
    day: date
    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    unpriced_calls: int


class LlmUsageRepository(BaseRepository[LlmUsage]):
    model = LlmUsage

    async def daily(
        self, *, from_day: date, to_day: date, group_by: UsageGroupBy
    ) -> list[DailyUsageRow]:
        """Per-day totals by station or model id, ordered by day then key. Null sums become 0."""
        key_col = LlmUsage.station if group_by == UsageGroupBy.STATION else LlmUsage.model_id
        stmt = (
            select(
                LlmUsage.usage_day,
                key_col,
                func.count(),
                func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                func.coalesce(func.sum(LlmUsage.output_tokens), 0),
                func.coalesce(func.sum(LlmUsage.cost_usd), 0),
                func.coalesce(func.sum(case((LlmUsage.cost_usd.is_(None), 1), else_=0)), 0),
            )
            .where(LlmUsage.usage_day >= from_day, LlmUsage.usage_day <= to_day)
            .group_by(LlmUsage.usage_day, key_col)
            .order_by(LlmUsage.usage_day, key_col)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            DailyUsageRow(
                day=row[0],
                key=row[1],
                calls=int(row[2]),
                input_tokens=int(cast("int", row[3])),
                output_tokens=int(cast("int", row[4])),
                cost_usd=Decimal(cast("Decimal", row[5])),
                unpriced_calls=int(cast("int", row[6])),
            )
            for row in rows
        ]

    async def for_item(self, item_id: int) -> list[LlmUsage]:
        stmt = (
            select(LlmUsage)
            .where(LlmUsage.work_item_id == item_id)
            .order_by(LlmUsage.created_at, LlmUsage.id)
        )
        return [*(await self.session.scalars(stmt)).all()]

    async def cost_for_day(self, day: date) -> Decimal:
        """Sum of known costs for the UTC day; 0 when there are none."""
        stmt = select(func.coalesce(func.sum(LlmUsage.cost_usd), 0)).where(
            LlmUsage.usage_day == day
        )
        return Decimal(cast("Decimal", (await self.session.execute(stmt)).scalar_one()))

    async def busy_since(self, role: LlmRole, since: datetime) -> tuple[int, int]:
        """``(sum of latency_ms, call count)`` for the role since ``since``."""
        stmt = select(func.coalesce(func.sum(LlmUsage.latency_ms), 0), func.count()).where(
            LlmUsage.role == role, LlmUsage.created_at >= since
        )
        row = (await self.session.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def purge_before(self, cutoff: datetime) -> int:
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(delete(LlmUsage).where(LlmUsage.created_at < cutoff)),
        )
        return int(result.rowcount)


class LlmBudgetAlertRepository(BaseRepository[LlmBudgetAlert]):
    model = LlmBudgetAlert

    def _pk(self) -> Any:
        return LlmBudgetAlert.alert_day

    async def for_day(self, day: date) -> LlmBudgetAlert | None:
        return await self.session.get(LlmBudgetAlert, day)
