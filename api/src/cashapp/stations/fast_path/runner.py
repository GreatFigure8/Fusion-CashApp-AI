"""The fast-path station: invoices already closed in Fusion, so attach the remittance and finish.

It never applies anything. When every invoice-like line points at a closed transaction and the
closing receipt(s) are known, the remittance is attached to each receipt through the shared
write-back, every line is recorded as previously applied and the item is finished. In every other
case the item continues on the normal path with the reason in its history.
"""

from decimal import Decimal
from typing import Any, ClassVar, Self

from cashapp.data.repositories.applications import LineResultRepository
from cashapp.data.repositories.customer_resolution import CustomerResolutionRepository
from cashapp.domain.config_keys import FUSION_RECEIPT_NOTE_MAX_CHARS
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.extraction import ExtractedLine
from cashapp.domain.stages import Stage
from cashapp.domain.status import HeaderResult, LineStatus, PaymentStatus, roll_up
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import FusionTransaction
from cashapp.pipeline.errors import StageError
from cashapp.pipeline.outcomes import Advance, Finish, StageOutcome
from cashapp.pipeline.roles import Container
from cashapp.pipeline.runner import RunnerDeps, StageContext, StageRunner, consumer_role
from cashapp.services.fast_path import (
    ClosingReceipts,
    LineMatch,
    closing_reason,
    find_closing_receipts,
    match_line_transactions,
)
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.validation import INVOICE_LIKE_KINDS, current_extraction
from cashapp.services.write_back import WriteBackDeps, write_back

_ZERO = Decimal("0.00")


def _lookup_lines(lines: list[ExtractedLine]) -> list[ExtractedLine]:
    """The lines the customer-resolution lookup used: invoice-like, with a transaction number."""
    return sorted(
        (
            line
            for line in lines
            if line.kind in INVOICE_LIKE_KINDS and line.transaction_number.strip()
        ),
        key=lambda line: line.line_no,
    )


def _write_back_error(exc: Exception, receipt_id: int, attached: list[int]) -> StageError:
    """Any write-back failure as ``WRITE_BACK_FAILED`` carrying ids and codes only."""
    if isinstance(exc, StageError):
        detail = {**exc.detail, "receipt_id": receipt_id, "attached_receipt_ids": attached}
        detail["stage"] = Stage.FAST_PATH.value
        return StageError(ErrorCode.WRITE_BACK_FAILED, detail)
    cause = exc.code.value if isinstance(exc, FusionError) else type(exc).__name__
    return StageError(
        ErrorCode.WRITE_BACK_FAILED,
        {
            "receipt_id": receipt_id,
            "attached_receipt_ids": attached,
            "cause": cause,
            "stage": Stage.FAST_PATH.value,
        },
    )


class FastPathRunner(StageRunner):
    stage: ClassVar[Stage] = Stage.FAST_PATH

    def __init__(
        self, deps: RunnerDeps, *, fusion: FusionClient, write_back_deps: WriteBackDeps
    ) -> None:
        super().__init__(deps)
        self._fusion = fusion
        self._write_back_deps = write_back_deps

    @classmethod
    def build(cls, container: Container) -> Self:
        return cls(
            RunnerDeps.from_container(container),
            fusion=container.resolve(FusionClient),
            write_back_deps=WriteBackDeps.from_container(container),
        )

    async def _transactions(
        self, ctx: StageContext, numbers: list[str], resolved: list[FusionTransaction]
    ) -> list[FusionTransaction]:
        if ctx.attempt == 0:
            return resolved  # the resolve station just looked these up
        try:  # a retry: a balance may have reopened since
            return await self._fusion.find_transactions(numbers)
        except FusionError as exc:
            raise StageError(
                exc.code, {"op": "find_transactions", "fusion_code": exc.fusion_code}
            ) from exc

    async def process(self, ctx: StageContext) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        resolution = await uow.repo(CustomerResolutionRepository).latest_for(item.id)
        if resolution is None:
            raise StageError(ErrorCode.CUSTOMER_NOT_FOUND, {"reason": "no_resolution"})
        extraction = await current_extraction(uow, item.id)
        if extraction is None:
            raise StageError(ErrorCode.EXTRACTION_FAILED, {"reason": "no_extraction"})

        lines = _lookup_lines(list(extraction.lines))
        transactions = await self._transactions(
            ctx, [line.transaction_number.strip() for line in lines], resolution.transactions
        )
        match = match_line_transactions(lines, transactions)
        closing = await find_closing_receipts(
            match.transactions(),
            self._fusion,
            unmatched_line_nos=match.unmatched_line_nos,
            ambiguous_line_nos=match.ambiguous_line_nos,
        )
        if not closing.all_closed:
            return self._not_eligible(match, closing, len(lines))
        if not closing.complete:
            return self._undetermined(closing)
        return await self._take(ctx, match, closing)

    @staticmethod
    def _not_eligible(match: LineMatch, closing: ClosingReceipts, lookup_lines: int) -> Advance:
        total = len(match.transactions()) + len(match.unmatched_line_nos)
        note = (
            f"fast path not taken: {len(closing.open_numbers) + len(match.unmatched_line_nos)}"
            f" of {max(total, lookup_lines)} transactions open or unmatched"
        )
        return Advance(
            Stage.MATCH_RECEIPT,
            note=note,
            payload={
                "fast_path": "not_eligible",
                "open": list(closing.open_numbers),
                "unmatched_line_nos": list(match.unmatched_line_nos),
                "ambiguous_line_nos": list(match.ambiguous_line_nos),
            },
        )

    @staticmethod
    def _undetermined(closing: ClosingReceipts) -> Advance:
        numbers = ", ".join(closing.undetermined_numbers) or "none found"
        return Advance(
            Stage.MATCH_RECEIPT,
            note=f"fast path not taken: closing receipt undetermined for {numbers}",
            payload={
                "fast_path": "undetermined",
                "undetermined": list(closing.undetermined_numbers),
                "receipt_ids": sorted(closing.receipt_ids),
            },
        )

    async def _take(
        self, ctx: StageContext, match: LineMatch, closing: ClosingReceipts
    ) -> StageOutcome:
        uow, item = ctx.uow, ctx.item
        receipt_ids = sorted(closing.receipt_ids)

        # Line results first: the shared write-back composes its receipt note from them, and
        # they are true whether or not the attach succeeds (nothing is applied by this station).
        line_results = uow.repo(LineResultRepository)
        statuses: list[LineStatus] = []
        total_due = _ZERO
        for entry in match.matched:
            transaction = entry.transaction
            receipts = closing.by_transaction.get(transaction.customer_trx_id, ())
            await line_results.upsert(
                item.id,
                entry.line_no,
                transaction_number=transaction.number,
                customer_trx_id=transaction.customer_trx_id,
                kind=transaction.kind.value,
                stated_amount=entry.line.amount_paid,
                balance_before=transaction.balance,
                applied_amount=_ZERO,
                line_status=LineStatus.ALLOCATION_PREVIOUSLY_APPLIED,
                error_code=None,
                reason="closed by receipt(s) " + ", ".join(str(r) for r in receipts),
            )
            statuses.append(LineStatus.ALLOCATION_PREVIOUSLY_APPLIED)
            if entry.line.amount_paid is not None:
                total_due += entry.line.amount_paid

        status = roll_up(
            HeaderResult(
                customer_found=True,
                payment_date_present=item.payment_date is not None,
                receipt_found=True,
                applied_total=_ZERO,
                total_due=total_due,
            ),
            statuses,
        )
        if status is not PaymentStatus.PAYMENT_PREVIOUSLY_APPLIED:
            raise StageError(
                ErrorCode.SYSTEM_DEAD_LETTER,
                {"reason": "fast_path_rollup_mismatch", "status": status.value},
            )
        # Set before the write-back, which refuses an item with no payment status.
        await uow.work_items.update(item, payment_status=status)

        note_max_chars = ctx.config.get(FUSION_RECEIPT_NOTE_MAX_CHARS)
        attached: list[int] = []
        for receipt_id in receipt_ids:
            try:
                await write_back(
                    uow,
                    item,
                    receipt_id,
                    mode="already_applied",
                    deps=self._write_back_deps,
                    note_max_chars=note_max_chars,
                    clock=ctx.clock,
                )
            except Exception as exc:
                raise _write_back_error(exc, receipt_id, list(attached)) from exc
            attached.append(receipt_id)

        payload: dict[str, Any] = {
            "fast_path": "taken",
            "receipt_ids": receipt_ids,
            "transactions": [
                {
                    "line_no": entry.line_no,
                    "transaction_number": entry.transaction.number,
                    "customer_trx_id": entry.transaction.customer_trx_id,
                    "kind": entry.transaction.kind.value,
                    "receipt_ids": list(
                        closing.by_transaction.get(entry.transaction.customer_trx_id, ())
                    ),
                }
                for entry in match.matched
            ],
            "line_count": len(match.matched),
        }
        await record_history(
            uow,
            item.id,
            HistoryEntry(
                action=HistoryAction.DECISION,
                reasoning=closing_reason(match, closing),
                payload=payload,
            ),
            clock=ctx.clock,
        )
        ctx.log.info(
            "fast path taken",
            extra={"receipt_count": len(receipt_ids), "line_count": len(match.matched)},
        )
        return Finish(
            status, note=f"already applied; remittance attached to {len(receipt_ids)} receipt(s)"
        )


ROLE = consumer_role(FastPathRunner, "fast-path")
build = ROLE.build
