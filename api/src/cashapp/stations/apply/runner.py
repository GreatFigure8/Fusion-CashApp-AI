"""The apply station: write each planned application to Fusion, one line at a time.

Every line is its own transaction: the ledger row, the line result, the history row and the claim
heartbeat are committed right after the Fusion call, so a crash mid-remittance keeps what was
already applied and the retry resumes at the first line that is not APPLIED. Before every call
the station re-checks the item's lock and Fusion's existing applications (idempotency).
"""

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Final, Self

from cashapp.data.models.applications import ApplicationLedger
from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.reservations import ReservationRepository
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.ledger import APPLIED_BY_SYSTEM, LedgerStatus
from cashapp.domain.money import to_money
from cashapp.domain.stages import Stage
from cashapp.domain.status import HeaderResult, InfoFlag, LineStatus, PaymentStatus, roll_up
from cashapp.domain.work_item import FixHints, HistoryAction
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.guard import WriteGuard
from cashapp.integrations.fusion.models import (
    ApplyRequest,
    ApplyResult,
    FusionMessage,
    FusionReceipt,
)
from cashapp.integrations.fusion.soap import accounting_date_for
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import is_locked_for_automation
from cashapp.services.matching.lines import apply_outcome_status, is_active_application
from cashapp.services.validation import current_extraction
from cashapp.workers.apply_gate import ReceiptApplyGate

REROUTE_CODES: Final = frozenset(
    {ErrorCode.FUSION_OVERAPPLY, ErrorCode.FUSION_ALREADY_APPLIED, ErrorCode.FUSION_GL_DATE}
)
RETRY_CODES: Final = frozenset({ErrorCode.FUSION_LOCKED, ErrorCode.FUSION_TRANSIENT})
_ISO_DATE: Final = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_REASON_MAX: Final = 500


def resolve_accounting_date(payment_date: date, today: date, fix_hints: FixHints | None) -> date:
    """The later of the payment date, today and any GL-date floor an auto-fix wrote."""
    base = accounting_date_for(payment_date, today)
    raw = (fix_hints or {}).get("gl_date_floor")
    if raw:
        try:
            return max(base, date.fromisoformat(str(raw)[:10]))
        except ValueError:
            return base
    return base


def _messages_json(messages: tuple[FusionMessage, ...]) -> list[dict[str, Any]]:
    return [{"code": m.code, "severity": m.severity, "text": m.text[:300]} for m in messages]


def _request_json(request: ApplyRequest) -> dict[str, Any]:
    return {
        "receipt_id": request.receipt_id,
        "customer_trx_id": request.customer_trx_id,
        "amount_applied": f"{request.amount_applied:.2f}",
        "receipt_currency": request.receipt_currency,
        "application_date": request.application_date.isoformat(),
        "accounting_date": request.accounting_date.isoformat(),
        "discount_amount": f"{request.discount_amount:.2f}"
        if request.discount_amount is not None
        else None,
    }


def _detail(
    row: ApplicationLedger, fusion_code: str | None, accounting_date: date
) -> dict[str, Any]:
    return {
        "ledger_id": row.id,
        "line_no": row.line_no,
        "receipt_id": row.receipt_id,
        "customer_trx_id": row.customer_trx_id,
        "fusion_code": fusion_code,
        "accounting_date": accounting_date.isoformat(),
    }


async def _persist_failure_state(
    ctx: StageContext,
    row: ApplicationLedger,
    code: ErrorCode,
    messages: tuple[FusionMessage, ...],
) -> None:
    """Keep the row PLANNED with the code and Fusion's answer, and commit what is done so far."""
    ledger = ctx.uow.repo(ApplicationLedgerRepository)
    await ledger.mark(
        row, LedgerStatus.PLANNED, error_code=code, response_messages=_messages_json(messages)
    )
    await ctx.uow.commit()


async def apply_one(
    ctx: StageContext,
    row: ApplicationLedger,
    *,
    fusion: FusionClient,
    gate: ReceiptApplyGate,
    receipt: FusionReceipt,
    accounting_date: date,
    claim_ttl: timedelta,
) -> None:
    """Apply one planned ledger row, or raise ``StageError`` after committing earlier lines."""
    uow, item = ctx.uow, ctx.item
    ledger = uow.repo(ApplicationLedgerRepository)
    results = uow.repo(LineResultRepository)
    async with gate.slot(row.receipt_id):
        now = ctx.clock.now()
        await ledger.reload_item(item)
        if is_locked_for_automation(item, now):
            await uow.commit()
            raise StageError(ErrorCode.FUSION_LOCKED, {"cause": "item_locked", "ledger_id": row.id})
        await uow.work_items.update(item, claim_expires_at=now + claim_ttl)

        # Idempotency: an earlier attempt may have landed (a crash, or an unknown outcome).
        try:
            existing = await fusion.list_receipt_applications(row.receipt_id)
        except FusionError as exc:
            await uow.commit()
            raise StageError(
                exc.code, {"op": "list_receipt_applications", "receipt_id": row.receipt_id}
            ) from exc
        owned = {
            r.fusion_application_id
            for r in await ledger.applied_for(item.id)
            if r.fusion_application_id is not None
        }
        present = next(
            (
                a
                for a in existing
                if is_active_application(a)
                and a.customer_trx_id == row.customer_trx_id
                and a.application_id not in owned
            ),
            None,
        )
        if present is not None:
            await _record_applied(
                ctx,
                row,
                application_id=present.application_id,
                amount=present.amount_applied,
                messages=(),
                note="already present in Fusion; not re-applied",
                accounting_date=accounting_date,
            )
            await uow.commit()
            return

        attempts: list[list[dict[str, Any]]] = []
        discount_sent = row.discount_amount
        while True:
            request = ApplyRequest(
                receipt_id=row.receipt_id,
                customer_trx_id=row.customer_trx_id,
                amount_applied=row.amount,
                receipt_currency=receipt.currency,
                application_date=accounting_date,
                accounting_date=accounting_date,
                discount_amount=row.discount_amount,
            )
            await ledger.update(row, request=_request_json(request))
            result: ApplyResult | None = None
            error: FusionError | None = None
            try:
                result = await fusion.apply_receipt(request)
            except FusionError as exc:
                error = exc

            if result is not None and result.ok:
                await _record_applied(
                    ctx,
                    row,
                    application_id=result.application_id,
                    amount=row.amount,
                    messages=result.raw_messages,
                    note="applied"
                    if not attempts
                    else "discount rejected by Fusion; applied cash only",
                    accounting_date=accounting_date,
                    discount_rejected=bool(attempts),
                    attempts=attempts,
                )
                await uow.commit()
                return

            if error is not None:
                code, fusion_code, message = error.code, error.fusion_code, error.message
                messages: tuple[FusionMessage, ...] = ()
                transient = error.retryable or error.outcome_unknown
            else:
                fault = result.fault if result is not None else None
                code = fault.code if fault is not None else ErrorCode.FUSION_FAULT
                fusion_code = fault.fusion_code if fault is not None else None
                message = fault.message if fault is not None else "apply not confirmed by Fusion"
                messages = result.raw_messages if result is not None else ()
                transient = False

            if (
                code is ErrorCode.FUSION_DISCOUNT_REJECTED
                and row.discount_amount is not None
                and not attempts
            ):
                # Transaction A: record the rejection and drop the discount before retrying, so a
                # crash resumes as a plain cash-only PLANNED row.
                attempts.append(_messages_json(messages))
                flags = [*item.info_flags]
                if InfoFlag.DISCOUNT_REJECTED_BY_FUSION.value not in flags:
                    flags.append(InfoFlag.DISCOUNT_REJECTED_BY_FUSION.value)
                item.info_flags = flags
                await ledger.update(
                    row,
                    discount_amount=None,
                    error_code=None,
                    response_messages={"attempts": attempts},
                )
                await record_history(
                    uow,
                    item.id,
                    HistoryEntry(
                        action=HistoryAction.FUSION_WRITE,
                        error_code=code,
                        reasoning=(
                            "Fusion rejected the earned discount (attempt 1); "
                            "re-applying the cash without it."
                        ),
                        payload={
                            **_detail(row, fusion_code, accounting_date),
                            "attempt": 1,
                            "discount_amount": discount_sent,
                            "messages": _messages_json(messages),
                        },
                    ),
                    clock=ctx.clock,
                )
                await uow.commit()
                # Transaction B: the same row through the same idempotency re-check and apply.
                try:
                    existing = await fusion.list_receipt_applications(row.receipt_id)
                except FusionError as exc:
                    raise StageError(
                        exc.code,
                        {"op": "list_receipt_applications", "receipt_id": row.receipt_id},
                    ) from exc
                landed = next(
                    (
                        a
                        for a in existing
                        if is_active_application(a)
                        and a.customer_trx_id == row.customer_trx_id
                        and a.application_id not in owned
                    ),
                    None,
                )
                if landed is not None:
                    await _record_applied(
                        ctx,
                        row,
                        application_id=landed.application_id,
                        amount=landed.amount_applied,
                        messages=(),
                        note="already present in Fusion; not re-applied",
                        accounting_date=accounting_date,
                    )
                    await uow.commit()
                    return
                continue
            break

        if code is ErrorCode.FUSION_WRITE_DISABLED:
            await uow.commit()
            raise StageError(code, {"op": "apply_receipt"})
        if code in REROUTE_CODES:
            await _persist_failure_state(ctx, row, code, messages)
            detail = _detail(row, fusion_code, accounting_date)
            if code is ErrorCode.FUSION_GL_DATE:
                match = _ISO_DATE.search(message)
                if match is not None:
                    detail["receipt_gl_date"] = match.group(1)
            raise StageError(code, detail)
        if code in RETRY_CODES or transient:
            await _persist_failure_state(ctx, row, code, messages)
            raise StageError(code, _detail(row, fusion_code, accounting_date))

        # A business fault on this line only: fail it and let the other lines go through.
        await ledger.mark(
            row,
            LedgerStatus.FAILED,
            error_code=code,
            response_messages=_messages_json(messages),
        )
        await results.upsert(
            item.id,
            row.line_no,
            line_status=apply_outcome_status(None, applied=False),
            error_code=code,
            reason=message[:_REASON_MAX],
        )
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.FUSION_WRITE,
                error_code=code,
                reasoning="Fusion rejected the application; the line is marked failed.",
                payload=_detail(row, fusion_code, accounting_date),
            ),
            clock=ctx.clock,
        )
        await uow.commit()


async def _record_applied(
    ctx: StageContext,
    row: ApplicationLedger,
    *,
    application_id: int | None,
    amount: Decimal,
    messages: tuple[FusionMessage, ...],
    note: str,
    accounting_date: date,
    discount_rejected: bool = False,
    attempts: list[list[dict[str, Any]]] | None = None,
) -> None:
    """Mark the ledger row APPLIED and write the line result and history (no commit)."""
    uow, item = ctx.uow, ctx.item
    ledger = uow.repo(ApplicationLedgerRepository)
    results = uow.repo(LineResultRepository)
    response: Any = _messages_json(messages) if messages else row.response_messages
    if discount_rejected:
        response = {"attempts": [*(attempts or []), _messages_json(messages)]}
    await ledger.mark_applied(
        row,
        fusion_application_id=application_id,
        amount=amount,
        applied_at=ctx.clock.now(),
        applied_by=APPLIED_BY_SYSTEM,
        response_messages=response,
    )
    current = await results.get_line(item.id, row.line_no)
    stated = current.stated_amount if current is not None else None
    target = current.target_status if current is not None else None
    if discount_rejected:
        balance = current.balance_before if current is not None else None
        short = balance is None or abs(amount) < abs(balance)
        target = LineStatus.ALLOCATION_APPLIED_SHORT_PAY if short else LineStatus.ALLOCATION_APPLIED
    await results.upsert(
        item.id,
        row.line_no,
        line_status=apply_outcome_status(target, applied=True),
        applied_amount=amount,
        discount_amount=row.discount_amount,
        residual=to_money(abs(stated) - abs(amount)) if stated is not None else None,
        error_code=None,
        reason=note,
    )
    await record_history(
        uow,
        item.id,
        HistoryEntry(
            action=HistoryAction.FUSION_WRITE,
            reasoning=f"Receipt applied to transaction: {note}.",
            payload={
                "ledger_id": row.id,
                "line_no": row.line_no,
                "receipt_id": row.receipt_id,
                "customer_trx_id": row.customer_trx_id,
                "amount": amount,
                "discount_amount": row.discount_amount,
                "application_id": application_id,
                "accounting_date": accounting_date.isoformat(),
                **({"attempt": 2} if discount_rejected else {}),
            },
        ),
        clock=ctx.clock,
    )


class ApplyRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.APPLY

    def __init__(
        self,
        deps: RunnerDeps,
        *,
        fusion: FusionClient,
        gate: ReceiptApplyGate,
        guard: WriteGuard,
    ) -> None:
        super().__init__(deps)
        self._fusion = fusion
        self._gate = gate
        self._guard = guard

    @classmethod
    def build(cls, container: Container) -> Self:
        fusion = container.resolve(FusionClient)
        return cls(
            RunnerDeps.from_container(container),
            fusion=fusion,
            gate=container.resolve(ReceiptApplyGate),
            guard=WriteGuard.from_runtime(container.runtime, fusion.pod_name),
        )

    async def process(self, ctx: StageContext) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        try:
            await self._guard.check("apply_receipt")
        except FusionError as exc:
            raise StageError(exc.code, {"op": "apply_receipt"}, exc.message) from exc

        reservation = await uow.repo(ReservationRepository).active_for_item(item.id)
        if reservation is None:
            raise StageError(ErrorCode.RECEIPT_NOT_YET_AVAILABLE, {"reason": "no_reservation"})
        extraction = await current_extraction(uow, item.id)
        if extraction is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_adjudication"})
        payment_date = item.payment_date or extraction.payment_date.value
        if payment_date is None:
            raise StageError(ErrorCode.MISSING_PAYMENT_DATE, {"reason": "no_payment_date"})
        try:
            receipt = await self._fusion.get_receipt(reservation.receipt_id)
        except FusionError as exc:
            raise StageError(
                exc.code, {"op": "get_receipt", "receipt_id": reservation.receipt_id}, exc.message
            ) from exc
        accounting_date = resolve_accounting_date(
            payment_date, ctx.clock.now().date(), item.fix_hints
        )

        ledger = uow.repo(ApplicationLedgerRepository)
        for row in await ledger.planned_for(item.id):
            await apply_one(
                ctx,
                row,
                fusion=self._fusion,
                gate=self._gate,
                receipt=receipt,
                accounting_date=accounting_date,
                claim_ttl=self.deps.claim_ttl,
            )

        header_amount = item.payment_amount or extraction.payment_amount.value
        status = await self._roll_up(ctx, header_amount)
        await uow.repo(ReservationRepository).consume(item.id, now=ctx.clock.now())
        return Advance(Stage.WRITE_BACK, note=status.value)

    async def _roll_up(self, ctx: StageContext, header_amount: Decimal | None) -> PaymentStatus:
        uow, item = ctx.uow, ctx.item
        results = uow.repo(LineResultRepository)
        line_rows = await results.for_item(item.id)

        # A merged duplicate line takes its primary line's final status.
        final = {r.line_no: r for r in line_rows if r.line_status is not None}
        for line in line_rows:
            primary = final.get(line.merged_into) if line.merged_into is not None else None
            if line.line_status is None and primary is not None:
                await results.upsert(
                    item.id,
                    line.line_no,
                    line_status=primary.line_status,
                    error_code=primary.error_code,
                    reason=f"merged into line {primary.line_no}",
                )
        line_rows = await results.for_item(item.id)
        statuses: list[LineStatus] = [r.line_status for r in line_rows if r.line_status is not None]

        applied = await uow.repo(ApplicationLedgerRepository).applied_for(item.id)
        applied_total = sum((r.amount for r in applied), Decimal("0.00"))
        if header_amount is not None:
            total_due = header_amount
        else:
            total_due = sum(
                (
                    -abs(r.stated_amount) if r.kind == "CREDIT_MEMO" else r.stated_amount
                    for r in line_rows
                    if r.stated_amount is not None and r.merged_into is None
                ),
                Decimal("0.00"),
            )
        header = HeaderResult(
            customer_found=True,
            payment_date_present=True,
            receipt_found=True,
            applied_total=to_money(applied_total),
            total_due=to_money(total_due),
        )
        status = roll_up(header, statuses)
        await uow.work_items.update(item, payment_status=status)
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.DECISION,
                reasoning=f"Payment status {status.value}, derived from the line results.",
                payload={
                    "lines": [
                        {
                            "line_no": r.line_no,
                            "transaction_number": r.transaction_number,
                            "status": r.line_status.value if r.line_status else None,
                            "applied": r.applied_amount,
                            "error_code": r.error_code.value if r.error_code else None,
                        }
                        for r in line_rows
                    ],
                    "applied_total": header.applied_total,
                    "payment_status": status.value,
                },
            ),
            clock=ctx.clock,
        )
        return status
