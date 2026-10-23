"""``MetricsService``: the one owner of the progress aggregates.

The dashboard router, the chat tool ``metrics.read`` and the progress reports all call this class,
so one screen can never show two figures for one thing. Every query goes through
``MetricsQueryRepository``. Nothing here commits.

Definitions (each window is the half-open ``[start, end)`` from ``window_bounds``):

* receipts matched: distinct work items with a receipt reservation in status ACTIVE or CONSUMED
  and at least one APPLIED ledger row applied in the window. RELEASED and REVERSED do not count.
* money by currency: per work-item currency, the sum of the signed APPLIED ledger amounts in the
  window, the distinct receipts, and the sum of the residuals of those items' applied lines. A
  currency is never mixed into another.
* automation rate: items that reached DONE in the window with no history row by a USER, divided by
  all items that reached DONE in the window. None when none reached DONE.
* awaiting receipt (now): items in AWAITING_RECEIPT, the whole days since the oldest
  awaiting_since, and the configured aging limit.
* open exceptions (now): ESCALATED items, of which locked (unexpired lock) and dead-lettered.
* accuracy: only from human-corrected extractions; None with n 0 when there are none.
* cost unknown share: rows with a null cost divided by all rows, never imputed.
"""

import inspect
from datetime import datetime, timedelta

from cashapp.data.repositories.metrics import MetricsQueryRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock
from cashapp.domain.extraction import ReaderSlot
from cashapp.domain.llm_usage import LlmRole
from cashapp.domain.metrics import (
    CostBasis,
    MetricsWindow,
    ThroughputBucket,
    bucket_start,
    bucket_step,
    default_bucket,
    window_bounds,
)
from cashapp.services.config import ConfigSnapshot, RuntimeConfig
from cashapp.services.metrics.accuracy import differs, field_agreement
from cashapp.services.metrics.activity import to_activity
from cashapp.services.metrics.models import (
    ActivityEvent,
    AutofixOutcome,
    AwaitingReceipt,
    CurrencyTotal,
    ModelEfficiencyRow,
    OpenExceptions,
    ProgressSummary,
    ThroughputPoint,
)
from cashapp.services.metrics.rates import money, rate

_OCI_PROVIDER = "oci"
_READER_SLOTS = {LlmRole.READER_A: ReaderSlot.A, LlmRole.READER_B: ReaderSlot.B}


class MetricsService:
    def __init__(
        self, uow: UnitOfWork, *, clock: Clock, config: RuntimeConfig | ConfigSnapshot
    ) -> None:
        self._repo = MetricsQueryRepository(uow.session)
        self._clock = clock
        self._config = config

    async def _aging_limit_days(self) -> int:
        aging = self._config.aging()
        resolved = await aging if inspect.isawaitable(aging) else aging
        return resolved.awaiting_receipt_max_days

    async def summary(self, window: MetricsWindow) -> ProgressSummary:
        """Receipts matched, automation rate, awaiting receipt, open exceptions and the rates.

        Receipts matched is the distinct items with an ACTIVE or CONSUMED reservation and at least
        one line applied in the window. Automation rate is DONE items in the window with no USER
        history entry divided by all DONE items in the window (None when there are none).
        """
        now = self._clock.now()
        start, end = window_bounds(window, now)
        done_all, done_untouched = await self._repo.done_counts(start, end)
        awaiting_count, oldest = await self._repo.awaiting()
        total, locked, dead = await self._repo.open_exceptions(now)
        autofix = await self._repo.autofix_by_code(start, end)
        human, model = await self._repo.adjudication_origin_counts(start, end)
        return ProgressSummary(
            window=window,
            start=start,
            end=end,
            receipts_matched=await self._repo.receipts_matched(start, end),
            done_items=done_all,
            automation_rate=rate(done_untouched, done_all),
            awaiting_receipt=AwaitingReceipt(
                count=awaiting_count,
                oldest_age_days=(max((now - oldest).days, 0) if oldest is not None else None),
                aging_limit_days=await self._aging_limit_days(),
            ),
            open_exceptions=OpenExceptions(total=total, locked=locked, dead_lettered=dead),
            autofix_rate=rate(sum(r.fixed for r in autofix), sum(r.attempted for r in autofix)),
            human_correction_rate=rate(human, model),
        )

    async def money_by_currency(self, window: MetricsWindow) -> list[CurrencyTotal]:
        """Per currency: the signed applied total, distinct receipts and residual. Never summed
        across currencies."""
        start, end = window_bounds(window, self._clock.now())
        return [
            CurrencyTotal(
                currency=row.currency,
                amount=money(row.amount),
                receipts=row.receipts,
                residual=money(row.residual),
            )
            for row in await self._repo.applied_by_currency(start, end)
        ]

    async def throughput(
        self, window: MetricsWindow, bucket: ThroughputBucket | None = None
    ) -> list[ThroughputPoint]:
        """Applied and escalated counts per UTC bucket; every bucket in the window is present."""
        chosen = bucket or default_bucket(window)
        start, end = window_bounds(window, self._clock.now())
        rows = await self._repo.throughput(start, end)
        applied: dict[datetime, int] = {}
        escalated: dict[datetime, int] = {}
        for at in rows.applied:
            key = bucket_start(at, chosen)
            applied[key] = applied.get(key, 0) + 1
        for at in rows.escalated:
            key = bucket_start(at, chosen)
            escalated[key] = escalated.get(key, 0) + 1
        points: list[ThroughputPoint] = []
        step: timedelta = bucket_step(chosen)
        cursor = bucket_start(start, chosen)
        while cursor < end:
            points.append(
                ThroughputPoint(
                    at=cursor, applied=applied.get(cursor, 0), escalated=escalated.get(cursor, 0)
                )
            )
            cursor += step
        return points

    async def autofix_outcomes(self, window: MetricsWindow) -> list[AutofixOutcome]:
        """Per error code: items attempted, items no longer stuck on it, and the fixed rate."""
        start, end = window_bounds(window, self._clock.now())
        return [
            AutofixOutcome(
                error_code=row.error_code,
                count=row.attempted,
                fixed=row.fixed,
                rate=rate(row.fixed, row.attempted),
            )
            for row in await self._repo.autofix_by_code(start, end)
        ]

    async def model_efficiency(self, window: MetricsWindow) -> list[ModelEfficiencyRow]:
        """Per (role, model): calls, cost with its null-cost share (never imputed), adjudicator
        agreement, and, only where people corrected, accuracy with its n."""
        start, end = window_bounds(window, self._clock.now())
        usage = await self._repo.usage_by_role_model(start, end)
        agreed, both = await self._repo.adjudication_agreement(start, end)
        agreement = rate(agreed, both)
        pairs = await self._repo.human_corrected_pairs(start, end)
        reader_ok = await self._repo.reader_ok_counts(start, end)

        matched: dict[ReaderSlot, int] = {ReaderSlot.A: 0, ReaderSlot.B: 0}
        total: dict[ReaderSlot, int] = {ReaderSlot.A: 0, ReaderSlot.B: 0}
        n: dict[ReaderSlot, int] = {ReaderSlot.A: 0, ReaderSlot.B: 0}
        corrected: dict[ReaderSlot, int] = {ReaderSlot.A: 0, ReaderSlot.B: 0}
        for pair in pairs:
            for slot, reading in ((ReaderSlot.A, pair.reading_a), (ReaderSlot.B, pair.reading_b)):
                if reading is None:
                    continue
                hit, fields = field_agreement(reading, pair.final)
                matched[slot] += hit
                total[slot] += fields
                n[slot] += 1
                if differs(reading, pair.final):
                    corrected[slot] += 1

        rows: list[ModelEfficiencyRow] = []
        for row in usage:
            cluster = row.provider == _OCI_PROVIDER
            slot = _READER_SLOTS.get(row.role)
            rows.append(
                ModelEfficiencyRow(
                    role=row.role,
                    model_id=row.model_id,
                    calls=row.calls,
                    cost_basis=CostBasis.CLUSTER if cluster else CostBasis.PER_CALL,
                    cost_usd=None if cluster else money(row.cost_usd),
                    cost_unknown_share=None if cluster else rate(row.null_cost_calls, row.calls),
                    agreement_rate=agreement if row.role is LlmRole.ADJUDICATOR else None,
                    human_correction_rate=(
                        rate(corrected[slot], reader_ok.get(slot, 0)) if slot else None
                    ),
                    accuracy=rate(matched[slot], total[slot]) if slot else None,
                    accuracy_n=n[slot] if slot else 0,
                )
            )
        return rows

    async def recent_activity(
        self, limit: int = 50, *, after_id: int | None = None
    ) -> list[ActivityEvent]:
        """Newest first; with ``after_id``, the events after it in ascending order."""
        return to_activity(await self._repo.activity(limit, after_id))
