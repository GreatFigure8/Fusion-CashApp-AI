"""API contracts for the operations reports. Separate from the ORM and the service dataclasses."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    field_validator,
)

from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import CurrencyCode, MoneyStr
from cashapp.domain.reports import (
    GENERATED_BY_CUTOVER,
    HtmlReportKind,
    ReportSection,
    ReportWindow,
)
from cashapp.domain.status import LineStatus
from cashapp.services.reports.html_service import ReportExportInfo
from cashapp.services.reports.models import (
    DailySummary,
    PartiallyPaidRow,
    ReportRunInfo,
)

PercentStr = Annotated[
    Decimal,
    PlainSerializer(lambda d: f"{d:.1f}", return_type=str, when_used="json"),
]

# A plain address check: the API has no e-mail validator dependency, and SMTP rejects the rest.
EmailAddress = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        max_length=254,
        pattern=r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$",
    ),
]


class CurrencyAmountOut(BaseModel):
    currency: CurrencyCode
    amount: MoneyStr


class ErrorCodeCountOut(BaseModel):
    error_code: ErrorCode
    count: int


class AgingBucketOut(BaseModel):
    key: str
    label: str
    count: int


class LastGeneratedOut(BaseModel):
    at: dt.datetime
    by: str
    by_kind: Literal["user", "cutover"]


class DailySummaryOut(BaseModel):
    date: dt.date
    items_in: int
    completed: int
    auto_applied: int
    auto_applied_pct: PercentStr | None
    applied_by_currency: list[CurrencyAmountOut]
    failures_by_error_code: list[ErrorCodeCountOut]
    aging_buckets: list[AgingBucketOut]
    escalations: int
    has_activity: bool

    @classmethod
    def of(cls, summary: DailySummary) -> "DailySummaryOut":
        return cls(
            date=summary.day,
            items_in=summary.items_in,
            completed=summary.completed,
            auto_applied=summary.auto_applied,
            auto_applied_pct=summary.auto_applied_pct,
            applied_by_currency=[
                CurrencyAmountOut(currency=row.currency, amount=row.amount)
                for row in summary.applied_by_currency
            ],
            failures_by_error_code=[
                ErrorCodeCountOut(error_code=row.error_code, count=row.count)
                for row in summary.failures_by_error_code
            ],
            aging_buckets=[
                AgingBucketOut(key=row.key, label=row.label, count=row.count)
                for row in summary.aging_buckets
            ],
            escalations=summary.escalations,
            has_activity=summary.has_activity,
        )


class DailySummaryResponse(BaseModel):
    summary: DailySummaryOut
    last_generated: LastGeneratedOut | None
    emailed_to: list[str]
    emailed_at: dt.datetime | None
    cutover: str  # "07:00"

    @classmethod
    def of(
        cls, summary: DailySummary, info: ReportRunInfo | None, cutover: dt.time
    ) -> "DailySummaryResponse":
        cutover_text = f"{cutover:%H:%M}"
        last: LastGeneratedOut | None = None
        if info is not None:
            if info.generated_by == GENERATED_BY_CUTOVER:
                last = LastGeneratedOut(
                    at=info.generated_at,
                    by=f"first event after {cutover_text} cutover",
                    by_kind="cutover",
                )
            else:
                last = LastGeneratedOut(
                    at=info.generated_at, by=info.generated_by_name, by_kind="user"
                )
        return cls(
            summary=DailySummaryOut.of(summary),
            last_generated=last,
            emailed_to=list(info.emailed_to) if info is not None else [],
            emailed_at=info.emailed_at if info is not None else None,
            cutover=cutover_text,
        )


class PartiallyPaidRowOut(BaseModel):
    invoice_number: str
    customer_account_number: str | None
    customer_name: str | None
    currency: CurrencyCode
    original: MoneyStr
    paid: MoneyStr
    remaining: MoneyStr
    short_pay_reason: str
    line_status: LineStatus
    item_id: int

    @classmethod
    def of(cls, row: PartiallyPaidRow) -> "PartiallyPaidRowOut":
        return cls(
            invoice_number=row.invoice_number,
            customer_account_number=row.customer_account_number,
            customer_name=row.customer_name,
            currency=row.currency,
            original=row.original,
            paid=row.paid,
            remaining=row.remaining,
            short_pay_reason=row.short_pay_reason,
            line_status=row.line_status,
            item_id=row.item_id,
        )


class PartiallyPaidResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: dt.date = Field(alias="from")
    to: dt.date
    rows: list[PartiallyPaidRowOut]
    truncated: bool

    @classmethod
    def of(
        cls, first: dt.date, last: dt.date, rows: list[PartiallyPaidRow], truncated: bool
    ) -> "PartiallyPaidResponse":
        return cls.model_validate(
            {
                "from": first,
                "to": last,
                "rows": [PartiallyPaidRowOut.of(row) for row in rows],
                "truncated": truncated,
            }
        )


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    recipients: Annotated[list[EmailAddress], Field(min_length=1, max_length=50)] | None = None


class EmailResponse(BaseModel):
    date: dt.date
    emailed_to: list[str]
    emailed_at: dt.datetime


class HtmlExportRequest(BaseModel):
    """Body of ``POST /reports/html/export``: the same three fields the preview takes."""

    model_config = ConfigDict(extra="forbid")

    kind: HtmlReportKind
    window: ReportWindow
    sections: Annotated[list[ReportSection], Field(min_length=1, max_length=len(ReportSection))]

    @field_validator("sections")
    @classmethod
    def _unique(cls, value: list[ReportSection]) -> list[ReportSection]:
        return list(dict.fromkeys(value))


class ReportExportOut(BaseModel):
    id: int
    kind: HtmlReportKind
    window: ReportWindow
    sections: list[ReportSection]
    filename: str
    bytes: int
    actor_name: str
    at: dt.datetime

    @classmethod
    def of(cls, info: ReportExportInfo) -> "ReportExportOut":
        return cls(
            id=info.id,
            kind=info.kind,
            window=info.window,
            sections=list(info.sections),
            filename=info.filename,
            bytes=info.bytes,
            actor_name=info.actor_name,
            at=info.at,
        )


class ReportExportsResponse(BaseModel):
    data: list[ReportExportOut]
