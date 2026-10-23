"""The LLM usage ledger (one row per model call) and the once-per-day budget alert marker."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from cashapp.data.models.base import Base
from cashapp.data.types import MoneyNumeric, StrEnumType, UtcDateTime, identity_pk
from cashapp.domain.clock import utcnow
from cashapp.domain.llm_usage import LlmRole, UsageOutcome


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("IX_LLM_USAGE_DAY", "usage_day", "station"),
        Index("IX_LLM_USAGE_ITEM", "work_item_id", "created_at"),
        Index("IX_LLM_USAGE_ROLE_AT", "role", "created_at"),
    )

    id: Mapped[int] = identity_pk()
    work_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_item.id", name="FK_LLM_USAGE_WI"), nullable=True
    )
    station: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[LlmRole] = mapped_column(StrEnumType(LlmRole, 20), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6, asdecimal=True), nullable=True)
    outcome: Mapped[UsageOutcome] = mapped_column(StrEnumType(UsageOutcome, 10), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    usage_day: Mapped[date] = mapped_column(Date, nullable=False)  # UTC day of created_at
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utcnow)


class LlmBudgetAlert(Base):
    """One row per UTC day the budget was exceeded; the primary key makes the alert once per day."""

    __tablename__ = "llm_budget_alert"

    alert_day: Mapped[date] = mapped_column(Date, primary_key=True, autoincrement=False)
    limit_usd: Mapped[Decimal] = mapped_column(MoneyNumeric, nullable=False)
    total_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6, asdecimal=True), nullable=False)
    emitted_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
