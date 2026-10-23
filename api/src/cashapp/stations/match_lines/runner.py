"""The match-lines station: plan which remittance line goes to which Fusion transaction.

It reads fresh balances and the receipt's existing applications from Fusion, plans the steps with
the pure ``plan_lines`` and persists them as PLANNED ledger rows and draft line results. It writes
nothing to Fusion. Re-entry (after an over-apply or already-applied fault) plans again from fresh
data and reconciles ledger rows whose application has since appeared in Fusion.
"""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any, ClassVar, Self, cast

from cashapp.data.models.applications import ApplicationLedger, LineResult
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.data.repositories.reservations import ReservationRepository
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine
from cashapp.domain.ledger import APPLIED_BY_SYSTEM, LedgerStatus
from cashapp.domain.money import to_money
from cashapp.domain.stages import Stage
from cashapp.domain.status import LineStatus
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionApplication
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.matching.lines import (
    APPLICABLE_LINE_KINDS,
    LedgerRowView,
    LinePlan,
    index_transactions,
    number_key,
    plan_lines,
    reconcile_ledger,
)
from cashapp.services.validation import current_extraction


def _fusion_error(exc: FusionError, op: str, receipt_id: int) -> StageError:
    return StageError(exc.code, {"op": op, "receipt_id": receipt_id}, exc.message)


def _unique_numbers(lines: Sequence[ExtractedLine]) -> list[str]:
    seen: dict[str, str] = {}
    for line in lines:
        seen.setdefault(number_key(line.transaction_number), line.transaction_number.strip())
    return [n for n in seen.values() if n]


class MatchLinesRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.MATCH_LINES

    def __init__(self, deps: RunnerDeps, *, fusion: FusionClient) -> None:
        super().__init__(deps)
        self._fusion = fusion

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(RunnerDeps.from_container(container), fusion=container.resolve(FusionClient))

    async def process(self, ctx: StageContext) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        reservation = await uow.repo(ReservationRepository).active_for_item(item.id)
        if reservation is None:
            return Advance(Stage.MATCH_RECEIPT, note="no active reservation")
        receipt_id = reservation.receipt_id

        extraction = await current_extraction(uow, item.id)
        if extraction is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_adjudication"})
        resolution = await uow.repo(CustomerResolutionRepository).latest_for(item.id)
        if resolution is None:
            raise StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"reason": "no_resolution"})

        lines = [ln for ln in extraction.lines if ln.kind in APPLICABLE_LINE_KINDS]
        try:
            found = await self._fusion.find_transactions(_unique_numbers(lines))
            receipt = await self._fusion.get_receipt(receipt_id)
            existing = await self._fusion.list_receipt_applications(receipt_id)
        except FusionError as exc:
            raise _fusion_error(exc, "match_lines_read", receipt_id) from exc

        ledger = uow.repo(ApplicationLedgerRepository)
        results = uow.repo(LineResultRepository)

        rows = await ledger.for_item(item.id)
        reconciled = await self._reconcile(ctx, rows, existing, results)

        applied_rows = [r for r in rows if r.status is LedgerStatus.APPLIED]
        applied_trx = {r.customer_trx_id for r in applied_rows}
        owned_applications = {
            r.fusion_application_id for r in applied_rows if r.fusion_application_id is not None
        }
        owners = resolution.owners()
        transactions, ambiguous = index_transactions(found, lines, owners)
        todo = [
            ln
            for ln in lines
            if not (
                (t := transactions.get(number_key(ln.transaction_number))) is not None
                and t.customer_trx_id in applied_trx
            )
        ]
        currency = item.currency or receipt.currency
        header_amount = item.payment_amount or extraction.payment_amount.value
        if header_amount is not None:
            header_amount -= sum((r.amount for r in applied_rows), Decimal("0.00"))
        plan = plan_lines(
            todo,
            transactions,
            receipt.unapplied_amount,
            [a for a in existing if a.application_id not in owned_applications],
            currency,
            header_amount=header_amount,
            tolerance=ctx.config.matching().tolerance_for(currency),
            owners=owners,
            ambiguous=ambiguous,
        )

        await self._persist(
            ctx,
            plan,
            rows,
            receipt_id=receipt_id,
            receipt_number=reservation.receipt_number or receipt.receipt_number,
        )
        await self._record(ctx, plan, receipt_id, reconciled)
        ctx.log.info(
            "lines planned", extra={"steps": len(plan.steps), "verdicts": len(plan.results)}
        )
        return Advance(
            Stage.APPLY,
            note=f"{len(plan.steps)} application(s) planned",
            payload={"receipt_id": receipt_id, "planned": len(plan.steps)},
        )

    async def _reconcile(
        self,
        ctx: StageContext,
        rows: Sequence[ApplicationLedger],
        existing: Sequence[FusionApplication],
        results: LineResultRepository,
    ) -> list[dict[str, Any]]:
        """Mark ledger rows whose application now exists in Fusion as APPLIED."""
        ledger = ctx.uow.repo(ApplicationLedgerRepository)
        by_id = {r.id: r for r in rows}
        stored = {r.line_no: r for r in await results.for_item(ctx.item.id)}
        now = ctx.clock.now()
        done: list[dict[str, Any]] = []
        for rec in reconcile_ledger(cast("Sequence[LedgerRowView]", rows), existing):
            row = by_id[rec.ledger_id]
            await ledger.mark_applied(
                row,
                fusion_application_id=rec.application_id,
                amount=rec.amount_applied,
                applied_at=now,
                applied_by=APPLIED_BY_SYSTEM,
            )
            current: LineResult | None = stored.get(row.line_no)
            target = (
                current.target_status
                if current is not None and current.target_status is not None
                else LineStatus.ALLOCATION_APPLIED
            )
            stated = current.stated_amount if current is not None else None
            await results.upsert(
                ctx.item.id,
                row.line_no,
                line_status=target,
                applied_amount=rec.amount_applied,
                residual=to_money(abs(stated) - abs(rec.amount_applied))
                if stated is not None
                else None,
                error_code=None,
                reason="reconciled against existing Fusion application",
            )
            done.append({"ledger_id": row.id, "application_id": rec.application_id})
        for entry in done:
            await record_history(
                ctx.uow,
                ctx.item.id,
                HistoryEntry(
                    action=HistoryAction.DECISION,
                    error_code=ErrorCode.FUSION_ALREADY_APPLIED,
                    reasoning="reconciled against existing Fusion application",
                    payload=entry,
                ),
                clock=ctx.clock,
            )
        return done

    async def _persist(
        self,
        ctx: StageContext,
        plan: LinePlan,
        rows: Sequence[ApplicationLedger],
        *,
        receipt_id: int,
        receipt_number: str | None,
    ) -> None:
        item_id = ctx.item.id
        ledger = ctx.uow.repo(ApplicationLedgerRepository)
        results = ctx.uow.repo(LineResultRepository)

        planned_trx = {s.transaction.customer_trx_id for s in plan.steps}
        for row in rows:
            if row.status is LedgerStatus.PLANNED and row.customer_trx_id not in planned_trx:
                await ledger.mark(
                    row,
                    LedgerStatus.FAILED,
                    error_code=None,
                    response_messages=[{"note": "dropped on re-plan"}],
                )
        for seq, step in enumerate(plan.steps):
            await ledger.upsert_planned(
                item_id,
                line_no=step.line_no,
                receipt_id=receipt_id,
                receipt_number=receipt_number,
                customer_trx_id=step.transaction.customer_trx_id,
                amount=step.amount,
                apply_seq=seq,
                discount_amount=step.discount,
            )
            await results.upsert(
                item_id,
                step.line_no,
                transaction_number=step.transaction.number,
                customer_trx_id=step.transaction.customer_trx_id,
                kind=step.kind.value,
                stated_amount=step.stated_amount,
                balance_before=step.balance_before,
                applied_amount=None,
                discount_amount=step.discount,
                residual=None,
                line_status=None,
                target_status=step.target_status,
                merged_into=None,
                error_code=None,
                reason=None,
            )
        step_lines = {s.line_no for s in plan.steps}
        for draft in plan.results:
            pending = draft.merged_into is not None and draft.merged_into in step_lines
            await results.upsert(
                item_id,
                draft.line_no,
                transaction_number=draft.transaction_number or None,
                customer_trx_id=draft.customer_trx_id,
                kind=None,
                stated_amount=draft.stated_amount,
                balance_before=draft.balance_before,
                applied_amount=None,
                discount_amount=None,
                residual=None,
                line_status=None if pending else draft.line_status,
                target_status=draft.line_status if pending else None,
                merged_into=draft.merged_into,
                error_code=draft.error_code,
                reason=draft.reason[:1000],
            )

    async def _record(
        self,
        ctx: StageContext,
        plan: LinePlan,
        receipt_id: int,
        reconciled: Sequence[dict[str, Any]],
    ) -> None:
        verdicts: dict[str, int] = {}
        for draft in plan.results:
            if draft.merged_into is None:
                verdicts[draft.line_status.value] = verdicts.get(draft.line_status.value, 0) + 1
        await record_history(
            ctx.uow,
            ctx.item.id,
            HistoryEntry(
                action=HistoryAction.DECISION,
                reasoning=(
                    f"Planned {len(plan.steps)} application(s) against receipt {receipt_id}; "
                    f"{sum(verdicts.values())} line(s) not applicable."
                ),
                payload={
                    "receipt_id": receipt_id,
                    "planned": len(plan.steps),
                    "steps": [
                        {
                            "line_no": s.line_no,
                            "transaction_number": s.transaction.number,
                            "amount": s.amount,
                            "target_status": s.target_status.value,
                        }
                        for s in plan.steps
                    ],
                    "verdicts": verdicts,
                    "ignored_line_nos": list(plan.ignored_line_nos),
                    "duplicates": {str(k): list(v) for k, v in plan.duplicates.items()},
                    "receipt_remaining_after": plan.receipt_remaining_after,
                    "reconciled": len(reconciled),
                },
            ),
            clock=ctx.clock,
        )
