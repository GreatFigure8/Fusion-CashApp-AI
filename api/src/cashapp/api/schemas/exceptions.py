"""API contracts for the exception workbench: the worklist and the Fusion context of one item."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cashapp.api.schemas.locks import LockInfoOut
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.money import MoneyStr
from cashapp.domain.paging import Page
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import PaymentStatus
from cashapp.services.exceptions_query import ExceptionFilters, ExceptionRow
from cashapp.services.fusion_context import FusionContext

ExceptionSort = Literal[
    "age", "-age", "amount", "-amount", "payment_date", "-payment_date", "id", "-id"
]


class ExceptionListQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = Field(default=None, max_length=200)
    amount_min: MoneyStr | None = None
    amount_max: MoneyStr | None = None
    date_from: date | None = None
    date_to: date | None = None
    error_codes: list[ErrorCode] = Field(default_factory=list[ErrorCode])
    stage: Stage | None = None
    locked_by_me: bool = False
    include_auto_applied: bool = False
    include_archived: bool = False
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    sort: ExceptionSort = "-age"

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> Self:
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min must not be greater than amount_max")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must not be after date_to")
        return self

    def to_filters(self) -> ExceptionFilters:
        return ExceptionFilters(
            q=self.q.strip() if self.q and self.q.strip() else None,
            amount_min=self.amount_min,
            amount_max=self.amount_max,
            date_from=self.date_from,
            date_to=self.date_to,
            error_codes=tuple(self.error_codes),
            stage=self.stage,
            locked_by_me=self.locked_by_me,
            include_auto_applied=self.include_auto_applied,
            include_archived=self.include_archived,
            page=self.page,
            page_size=self.page_size,
            sort=self.sort,
        )


class ExceptionRowOut(BaseModel):
    id: int
    payer_name: str | None
    amount: MoneyStr | None
    currency: str | None
    payment_date: date | None
    error_code: ErrorCode | None
    autofix_tried: int
    autofix_limit: int
    age_s: int
    stage: Stage
    state: ItemState
    payment_status: PaymentStatus | None
    lock: LockInfoOut | None

    @classmethod
    def from_row(cls, row: ExceptionRow) -> Self:
        item = row.item
        return cls(
            id=item.id,
            payer_name=item.payer_name,
            amount=item.payment_amount,
            currency=item.currency,
            payment_date=item.payment_date,
            error_code=item.last_error_code,
            autofix_tried=row.autofix_tried,
            autofix_limit=row.autofix_limit,
            age_s=row.age_s,
            stage=item.stage,
            state=item.state,
            payment_status=item.payment_status,
            lock=LockInfoOut.from_info(row.lock),
        )


class ExceptionListOut(BaseModel):
    items: list[ExceptionRowOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_page(cls, page: Page[ExceptionRow], *, number: int, page_size: int) -> Self:
        return cls(
            items=[ExceptionRowOut.from_row(row) for row in page.items],
            total=page.total,
            page=number,
            page_size=page_size,
        )


class CustomerSiteOut(BaseModel):
    site_number: str
    purpose: str | None
    location: str | None
    address: str | None


class RelationshipOut(BaseModel):
    account_number: str
    name: str | None
    directions: list[Literal["INBOUND", "OUTBOUND"]]


class CustomerContextOut(BaseModel):
    account_number: str
    name: str
    bill_to_site: CustomerSiteOut | None
    location: str | None
    relationships: list[RelationshipOut]


class InvoiceContextOut(BaseModel):
    number: str
    customer_trx_id: int
    bill_to_customer: str | None
    bill_to_site: str | None
    original_amount: MoneyStr
    remaining: MoneyStr
    currency: str
    status: str


class CreditMemoApplicationOut(BaseModel):
    application_id: int
    receipt_id: int
    amount_applied: MoneyStr
    apply_date: date
    status: str


class CreditMemoHistoryOut(BaseModel):
    number: str
    customer_trx_id: int
    original: MoneyStr
    remaining: MoneyStr
    currency: str
    applications: list[CreditMemoApplicationOut]


class CandidateReceiptOut(BaseModel):
    receipt_number: str
    receipt_id: int
    receipt_date: date | None
    amount: MoneyStr | None
    remaining: MoneyStr | None
    currency: str | None
    customer: str | None
    score: float
    qualifies: bool
    chosen: bool
    stale: bool


class AutofixAttemptOut(BaseModel):
    at: datetime
    code: ErrorCode | None
    decision: str | None
    attempt: int | None
    limit: int | None
    reasoning: str | None


class LedgerApplicationOut(BaseModel):
    ledger_id: int
    line_no: int
    receipt_id: int
    receipt_number: str | None
    customer_trx_id: int
    transaction_number: str | None
    amount: MoneyStr
    status: str
    fusion_application_id: int | None
    applied_at: datetime | None
    reversed_at: datetime | None
    reversed_by: str | None
    reversal_reason: str | None


class ContextWarningOut(BaseModel):
    section: Literal["customer", "invoices", "credit_memos", "receipts"]
    code: ErrorCode
    message: str


class FusionContextOut(BaseModel):
    item_id: int
    customer: CustomerContextOut | None
    invoices: list[InvoiceContextOut]
    credit_memo_history: list[CreditMemoHistoryOut]
    candidate_receipts: list[CandidateReceiptOut]
    autofix_attempts: list[AutofixAttemptOut]
    applications: list[LedgerApplicationOut]
    warnings: list[ContextWarningOut]
    built_at: datetime

    @classmethod
    def from_context(cls, ctx: FusionContext) -> Self:
        customer = ctx.customer
        return cls(
            item_id=ctx.item_id,
            customer=(
                CustomerContextOut(
                    account_number=customer.account_number,
                    name=customer.name,
                    bill_to_site=(
                        CustomerSiteOut(
                            site_number=customer.bill_to_site.site_number,
                            purpose=customer.bill_to_site.purpose,
                            location=customer.bill_to_site.location,
                            address=customer.bill_to_site.address,
                        )
                        if customer.bill_to_site
                        else None
                    ),
                    location=customer.location,
                    relationships=[
                        RelationshipOut(
                            account_number=r.account_number,
                            name=r.name,
                            directions=list(r.directions),
                        )
                        for r in customer.relationships
                    ],
                )
                if customer
                else None
            ),
            invoices=[
                InvoiceContextOut(
                    number=i.number,
                    customer_trx_id=i.customer_trx_id,
                    bill_to_customer=i.bill_to_customer,
                    bill_to_site=i.bill_to_site,
                    original_amount=i.original_amount,
                    remaining=i.remaining,
                    currency=i.currency,
                    status=i.status,
                )
                for i in ctx.invoices
            ],
            credit_memo_history=[
                CreditMemoHistoryOut(
                    number=h.number,
                    customer_trx_id=h.customer_trx_id,
                    original=h.original,
                    remaining=h.remaining,
                    currency=h.currency,
                    applications=[
                        CreditMemoApplicationOut(
                            application_id=a.application_id,
                            receipt_id=a.receipt_id,
                            amount_applied=a.amount_applied,
                            apply_date=a.apply_date,
                            status=a.status,
                        )
                        for a in h.applications
                    ],
                )
                for h in ctx.credit_memo_history
            ],
            candidate_receipts=[
                CandidateReceiptOut(
                    receipt_number=c.receipt_number,
                    receipt_id=c.receipt_id,
                    receipt_date=c.receipt_date,
                    amount=c.amount,
                    remaining=c.remaining,
                    currency=c.currency,
                    customer=c.customer,
                    score=c.score,
                    qualifies=c.qualifies,
                    chosen=c.chosen,
                    stale=c.stale,
                )
                for c in ctx.candidate_receipts
            ],
            autofix_attempts=[
                AutofixAttemptOut(
                    at=a.at,
                    code=a.code,
                    decision=a.decision,
                    attempt=a.attempt,
                    limit=a.limit,
                    reasoning=a.reasoning,
                )
                for a in ctx.autofix_attempts
            ],
            applications=[
                LedgerApplicationOut(
                    ledger_id=a.ledger_id,
                    line_no=a.line_no,
                    receipt_id=a.receipt_id,
                    receipt_number=a.receipt_number,
                    customer_trx_id=a.customer_trx_id,
                    transaction_number=a.transaction_number,
                    amount=a.amount,
                    status=a.status,
                    fusion_application_id=a.fusion_application_id,
                    applied_at=a.applied_at,
                    reversed_at=a.reversed_at,
                    reversed_by=a.reversed_by,
                    reversal_reason=a.reversal_reason,
                )
                for a in ctx.applications
            ],
            warnings=[
                ContextWarningOut(section=w.section, code=w.code, message=w.message)
                for w in ctx.warnings
            ],
            built_at=ctx.built_at,
        )
