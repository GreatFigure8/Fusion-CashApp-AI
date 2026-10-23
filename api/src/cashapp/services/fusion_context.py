"""What Fusion's own screens make hard to see, assembled for one stuck item.

Customer and bill-to site, pay-on-behalf relationships, fresh invoice and credit memo balances,
candidate receipts and the applied ledger. Every Fusion section fails on its own: a Fusion outage
yields warnings, not a blank workbench. The client passed in is read-only.
"""

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Final, Literal

from cashapp.data.models.adjudication import AdjudicationPurged
from cashapp.data.models.work_item import WorkItem
from cashapp.data.repositories.adjudication import AdjudicationRepository
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.repositories.exceptions import ExceptionsRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import (
    FusionCustomer,
    FusionReceipt,
    FusionTransaction,
    TransactionKind,
)
from cashapp.services.locking import ItemNotFound

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS: Final = 60.0
CACHE_MAX_ENTRIES: Final = 512

WarningSection = Literal["customer", "invoices", "credit_memos", "receipts"]
Direction = Literal["INBOUND", "OUTBOUND"]
_DIRECTIONS: Final[tuple[Direction, ...]] = ("INBOUND", "OUTBOUND")


@dataclass(frozen=True, slots=True)
class CustomerSite:
    site_number: str
    purpose: str | None
    location: str | None
    address: str | None


@dataclass(frozen=True, slots=True)
class Relationship:
    account_number: str
    name: str | None
    directions: tuple[Direction, ...]


@dataclass(frozen=True, slots=True)
class CustomerContext:
    account_number: str
    name: str
    bill_to_site: CustomerSite | None
    location: str | None
    relationships: tuple[Relationship, ...]


@dataclass(frozen=True, slots=True)
class InvoiceContext:
    number: str
    customer_trx_id: int
    bill_to_customer: str | None
    bill_to_site: str | None
    original_amount: Decimal
    remaining: Decimal
    currency: str
    status: str


@dataclass(frozen=True, slots=True)
class CreditMemoApplication:
    application_id: int
    receipt_id: int
    amount_applied: Decimal
    apply_date: date
    status: str


@dataclass(frozen=True, slots=True)
class CreditMemoHistory:
    number: str
    customer_trx_id: int
    original: Decimal
    remaining: Decimal
    currency: str
    applications: tuple[CreditMemoApplication, ...]


@dataclass(frozen=True, slots=True)
class CandidateReceipt:
    receipt_number: str
    receipt_id: int
    receipt_date: date | None
    amount: Decimal | None
    remaining: Decimal | None
    currency: str | None
    customer: str | None
    score: float
    qualifies: bool
    chosen: bool
    stale: bool


@dataclass(frozen=True, slots=True)
class AutofixAttempt:
    at: datetime
    code: ErrorCode | None
    decision: str | None
    attempt: int | None
    limit: int | None
    reasoning: str | None


@dataclass(frozen=True, slots=True)
class LedgerApplication:
    ledger_id: int
    line_no: int
    receipt_id: int
    receipt_number: str | None
    customer_trx_id: int
    transaction_number: str | None
    amount: Decimal
    status: str
    fusion_application_id: int | None
    applied_at: datetime | None
    reversed_at: datetime | None
    reversed_by: str | None
    reversal_reason: str | None


@dataclass(frozen=True, slots=True)
class ContextWarning:
    section: WarningSection
    code: ErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class FusionContext:
    item_id: int
    customer: CustomerContext | None
    invoices: tuple[InvoiceContext, ...]
    credit_memo_history: tuple[CreditMemoHistory, ...]
    candidate_receipts: tuple[CandidateReceipt, ...]
    autofix_attempts: tuple[AutofixAttempt, ...]
    applications: tuple[LedgerApplication, ...]
    warnings: tuple[ContextWarning, ...]
    built_at: datetime


class FusionContextCache:
    """In-process TTL cache keyed on ``(item_id, version)``: a version bump is always a miss."""

    def __init__(
        self,
        *,
        ttl_s: float = CACHE_TTL_SECONDS,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Clock | None = None,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock: Clock = clock or SystemClock()
        self._entries: OrderedDict[tuple[int, int], tuple[datetime, FusionContext]] = OrderedDict()

    def get(self, item_id: int, version: int) -> FusionContext | None:
        entry = self._entries.get((item_id, version))
        if entry is None:
            return None
        stored_at, context = entry
        if (self._clock.now() - stored_at).total_seconds() >= self._ttl_s:
            del self._entries[(item_id, version)]
            return None
        return context

    def put(self, item_id: int, version: int, ctx: FusionContext) -> None:
        # Older versions of the same item can never be read again.
        for key in [k for k in self._entries if k[0] == item_id and k[1] != version]:
            del self._entries[key]
        self._entries[(item_id, version)] = (self._clock.now(), ctx)
        self._entries.move_to_end((item_id, version))
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


@dataclass(frozen=True, slots=True)
class _Candidate:
    receipt_number: str
    receipt_id: int
    score: float
    qualifies: bool
    chosen: bool
    receipt_date: date | None
    remaining: Decimal | None
    currency: str | None
    customer: str | None


@dataclass(slots=True)
class _DbPhase:
    """Everything read from the database, as plain values, before any Fusion call is made."""

    anchor: str | None
    numbers: list[str]
    candidates: list[_Candidate]
    attempts: tuple[AutofixAttempt, ...]
    applications: tuple[LedgerApplication, ...]
    warnings: list[ContextWarning] = field(default_factory=list[ContextWarning])


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _warning(section: WarningSection, exc: FusionError) -> ContextWarning:
    return ContextWarning(section=section, code=exc.code, message=exc.message)


class FusionContextService:
    def __init__(
        self,
        fusion: FusionClient,
        *,
        cache: FusionContextCache,
        clock: Clock | None = None,
        max_credit_memos: int = 20,
        max_receipts: int = 10,
        fusion_concurrency: int = 4,
    ) -> None:
        self._fusion = fusion
        self._cache = cache
        self._clock: Clock = clock or SystemClock()
        self._max_credit_memos = max_credit_memos
        self._max_receipts = max_receipts
        self._fusion_concurrency = fusion_concurrency

    async def build(self, uow: UnitOfWork, item_id: int) -> FusionContext:
        item = await uow.work_items.get(item_id)
        if item is None:
            raise ItemNotFound(item_id)
        version = item.version
        cached = self._cache.get(item_id, version)
        if cached is not None:
            return cached

        phase = await self._read_database(uow, item)
        # Release the connection: the Fusion reads below can take many seconds.
        await uow.rollback()

        semaphore = asyncio.Semaphore(self._fusion_concurrency)
        customer_task = self._customer(phase.anchor, phase.warnings)
        transactions_task = self._transactions(phase.numbers, semaphore, phase.warnings)
        receipts_task = self._receipts(phase.candidates, semaphore, phase.warnings)
        customer, (invoices, memo_history), receipts = await asyncio.gather(
            customer_task, transactions_task, receipts_task
        )

        context = FusionContext(
            item_id=item_id,
            customer=customer,
            invoices=invoices,
            credit_memo_history=memo_history,
            candidate_receipts=receipts,
            autofix_attempts=phase.attempts,
            applications=phase.applications,
            warnings=tuple(phase.warnings),
            built_at=self._clock.now(),
        )
        if not phase.warnings:
            self._cache.put(item_id, version, context)
        return context

    # ------------------------------------------------------------------ database phase

    async def _read_database(self, uow: UnitOfWork, item: WorkItem) -> _DbPhase:
        item_id = item.id
        fallback_anchor = item.customer_account_number
        resolution = await uow.repo(CustomerResolutionRepository).latest_for(item_id)
        anchor = resolution.anchor_customer_number if resolution else fallback_anchor

        numbers: list[str] = []
        adjudication = await uow.repo(AdjudicationRepository).latest_for(item_id)
        if adjudication is not None:
            try:
                for line in adjudication.result().final.lines:
                    numbers.append(line.transaction_number)
            except AdjudicationPurged:
                pass
        if resolution is not None:
            numbers.extend(t.number for t in resolution.transactions)
        numbers = _dedupe(n.strip() for n in numbers if n and n.strip())

        exceptions = uow.repo(ExceptionsRepository)
        candidate_rows = await exceptions.latest_match_candidates(item_id, limit=self._max_receipts)
        candidates = [
            _Candidate(
                receipt_number=row.receipt_number or str(row.receipt_id),
                receipt_id=row.receipt_id,
                score=row.score,
                qualifies=row.qualifies,
                chosen=row.chosen,
                receipt_date=row.receipt_date,
                remaining=row.unapplied_amount,
                currency=row.currency,
                customer=row.customer_account_number,
            )
            for row in candidate_rows
        ]
        receipt_numbers = {c.receipt_id: c.receipt_number for c in candidates}

        attempts = tuple(
            AutofixAttempt(
                at=row.at,
                code=row.error_code,
                decision=_str_or_none((row.payload or {}).get("decision")),
                attempt=_int_or_none((row.payload or {}).get("attempt")),
                limit=_int_or_none((row.payload or {}).get("limit")),
                reasoning=row.reasoning,
            )
            for row in await exceptions.autofix_attempts(item_id)
        )

        line_numbers = {
            row.line_no: row.transaction_number
            for row in await uow.repo(LineResultRepository).for_item(item_id)
        }
        applications = tuple(
            LedgerApplication(
                ledger_id=row.id,
                line_no=row.line_no,
                receipt_id=row.receipt_id,
                receipt_number=row.receipt_number or receipt_numbers.get(row.receipt_id),
                customer_trx_id=row.customer_trx_id,
                transaction_number=line_numbers.get(row.line_no),
                amount=row.amount,
                status=str(row.status),
                fusion_application_id=row.fusion_application_id,
                applied_at=row.applied_at,
                reversed_at=row.reversed_at,
                reversed_by=row.reversed_by,
                reversal_reason=row.reversal_reason,
            )
            for row in await uow.repo(ApplicationLedgerRepository).for_item(item_id)
        )
        return _DbPhase(
            anchor=anchor,
            numbers=numbers,
            candidates=candidates,
            attempts=attempts,
            applications=applications,
        )

    # ------------------------------------------------------------------ Fusion phase

    async def _customer(
        self, anchor: str | None, warnings: list[ContextWarning]
    ) -> CustomerContext | None:
        if not anchor:
            return None
        try:
            account: FusionCustomer = await self._fusion.get_customer_account(anchor)
        except FusionError as exc:
            warnings.append(_warning("customer", exc))
            return None
        relationships: list[Relationship] = []
        try:
            for rel in await self._fusion.customer_relationships([anchor]):
                relationships.append(
                    Relationship(
                        account_number=rel.related_account_number,
                        name=rel.related_account_name,
                        directions=tuple(d for d in _DIRECTIONS if d in rel.directions),
                    )
                )
        except FusionError as exc:
            warnings.append(_warning("customer", exc))
        site = next((s for s in account.sites if s.purpose == "BILL_TO"), None)
        if site is None and account.sites:
            site = account.sites[0]
        return CustomerContext(
            account_number=account.account_number,
            name=account.name,
            bill_to_site=(
                CustomerSite(
                    site_number=site.site_number,
                    purpose=site.purpose,
                    location=site.location,
                    address=site.address,
                )
                if site
                else None
            ),
            location=site.location if site else None,
            relationships=tuple(relationships),
        )

    async def _transactions(
        self,
        numbers: list[str],
        semaphore: asyncio.Semaphore,
        warnings: list[ContextWarning],
    ) -> tuple[tuple[InvoiceContext, ...], tuple[CreditMemoHistory, ...]]:
        if not numbers:
            return (), ()
        try:
            found = await self._fusion.find_transactions(numbers)
        except FusionError as exc:
            warnings.append(_warning("invoices", exc))
            return (), ()
        invoices = tuple(
            InvoiceContext(
                number=t.number,
                customer_trx_id=t.customer_trx_id,
                bill_to_customer=t.bill_to_customer_number,
                bill_to_site=t.bill_to_site,
                original_amount=t.original_amount,
                remaining=t.balance,
                currency=t.currency,
                status=t.status,
            )
            for t in found
            if t.kind == TransactionKind.INVOICE
        )
        memos = [t for t in found if t.kind == TransactionKind.CREDIT_MEMO][
            : self._max_credit_memos
        ]
        histories = await asyncio.gather(
            *(self._memo_history(memo, semaphore, warnings) for memo in memos)
        )
        return invoices, tuple(h for h in histories if h is not None)

    async def _memo_history(
        self,
        memo: FusionTransaction,
        semaphore: asyncio.Semaphore,
        warnings: list[ContextWarning],
    ) -> CreditMemoHistory | None:
        async with semaphore:
            try:
                applications = await self._fusion.list_transaction_applications(
                    memo.customer_trx_id
                )
            except FusionError as exc:
                warnings.append(_warning("credit_memos", exc))
                return None
        return CreditMemoHistory(
            number=memo.number,
            customer_trx_id=memo.customer_trx_id,
            original=memo.original_amount,
            remaining=memo.balance,
            currency=memo.currency,
            applications=tuple(
                CreditMemoApplication(
                    application_id=a.application_id,
                    receipt_id=a.receipt_id,
                    amount_applied=a.amount_applied,
                    apply_date=a.apply_date,
                    status=a.status,
                )
                for a in applications
            ),
        )

    async def _receipts(
        self,
        candidates: list[_Candidate],
        semaphore: asyncio.Semaphore,
        warnings: list[ContextWarning],
    ) -> tuple[CandidateReceipt, ...]:
        results = await asyncio.gather(*(self._receipt(c, semaphore) for c in candidates))
        stale = sum(1 for r in results if r.stale)
        if stale:
            warnings.append(
                ContextWarning(
                    section="receipts",
                    code=ErrorCode.FUSION_TRANSIENT,
                    message=f"{stale} receipt(s) could not be refreshed; stored values are shown.",
                )
            )
        return tuple(results)

    async def _receipt(
        self, candidate: _Candidate, semaphore: asyncio.Semaphore
    ) -> CandidateReceipt:
        fresh: FusionReceipt | None = None
        async with semaphore:
            try:
                fresh = await self._fusion.get_receipt(candidate.receipt_id)
            except FusionError:
                logger.warning("receipt refresh failed", extra={"receipt_id": candidate.receipt_id})
        if fresh is None:
            return CandidateReceipt(
                receipt_number=candidate.receipt_number,
                receipt_id=candidate.receipt_id,
                receipt_date=candidate.receipt_date,
                amount=None,
                remaining=candidate.remaining,
                currency=candidate.currency,
                customer=candidate.customer,
                score=candidate.score,
                qualifies=candidate.qualifies,
                chosen=candidate.chosen,
                stale=True,
            )
        return CandidateReceipt(
            receipt_number=fresh.receipt_number or candidate.receipt_number,
            receipt_id=candidate.receipt_id,
            receipt_date=fresh.receipt_date,
            amount=fresh.amount,
            remaining=fresh.unapplied_amount,
            currency=fresh.currency,
            customer=fresh.customer_account_number,
            score=candidate.score,
            qualifies=candidate.qualifies,
            chosen=candidate.chosen,
            stale=False,
        )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return [*seen]


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
