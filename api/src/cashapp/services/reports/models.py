"""Value objects of the operations reports. Frozen, so a stored payload and a live one compare."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Self

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import to_money
from cashapp.domain.reports import ReportKind
from cashapp.domain.status import LineStatus


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ErrorCodeCount:
    error_code: ErrorCode
    count: int


@dataclass(frozen=True, slots=True)
class AgingBucketCount:
    key: str
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    items_in: int
    completed: int
    auto_applied: int
    auto_applied_pct: Decimal | None
    applied_by_currency: tuple[CurrencyAmount, ...]
    failures_by_error_code: tuple[ErrorCodeCount, ...]
    aging_buckets: tuple[AgingBucketCount, ...]
    escalations: int
    has_activity: bool

    def to_payload(self) -> dict[str, Any]:
        """JSON-safe form stored on REPORT_RUN; Decimals travel as strings."""
        return {
            "day": self.day.isoformat(),
            "items_in": self.items_in,
            "completed": self.completed,
            "auto_applied": self.auto_applied,
            "auto_applied_pct": None
            if self.auto_applied_pct is None
            else str(self.auto_applied_pct),
            "applied_by_currency": [
                {"currency": row.currency, "amount": str(row.amount)}
                for row in self.applied_by_currency
            ],
            "failures_by_error_code": [
                {"error_code": row.error_code.value, "count": row.count}
                for row in self.failures_by_error_code
            ],
            "aging_buckets": [
                {"key": row.key, "label": row.label, "count": row.count}
                for row in self.aging_buckets
            ],
            "escalations": self.escalations,
            "has_activity": self.has_activity,
        }

    @classmethod
    def from_payload(cls, p: Mapping[str, Any]) -> Self:
        pct = p["auto_applied_pct"]
        return cls(
            day=date.fromisoformat(p["day"]),
            items_in=int(p["items_in"]),
            completed=int(p["completed"]),
            auto_applied=int(p["auto_applied"]),
            auto_applied_pct=None if pct is None else Decimal(pct),
            applied_by_currency=tuple(
                CurrencyAmount(row["currency"], to_money(Decimal(row["amount"])))
                for row in p["applied_by_currency"]
            ),
            failures_by_error_code=tuple(
                ErrorCodeCount(ErrorCode(row["error_code"]), int(row["count"]))
                for row in p["failures_by_error_code"]
            ),
            aging_buckets=tuple(
                AgingBucketCount(row["key"], row["label"], int(row["count"]))
                for row in p["aging_buckets"]
            ),
            escalations=int(p["escalations"]),
            has_activity=bool(p["has_activity"]),
        )


@dataclass(frozen=True, slots=True)
class PartiallyPaidRow:
    invoice_number: str
    customer_account_number: str | None
    customer_name: str | None
    currency: str
    original: Decimal
    paid: Decimal
    remaining: Decimal
    short_pay_reason: str
    line_status: LineStatus
    item_id: int


@dataclass(frozen=True, slots=True)
class ReportRunInfo:
    id: int
    kind: ReportKind
    report_date: date
    generated_at: datetime
    generated_by: str
    generated_by_name: str
    emailed_to: tuple[str, ...]
    emailed_at: datetime | None
