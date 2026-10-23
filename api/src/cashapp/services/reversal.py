"""Reverse an automated application in Fusion, from the workbench, with a full audit trail.

Only ledger rows this system made (``APPLIED`` with a Fusion application id) can be reversed. Every
refusal happens before any Fusion write. The service flushes and never commits; the router commits.
"""

import dataclasses
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Final

from cashapp.data.repositories.applications import (
    ApplicationLedgerRepository,
    LineResultRepository,
)
from cashapp.data.repositories.reservations import ReservationRepository
from cashapp.data.uow import UnitOfWork
from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.error_codes import ErrorCode
from cashapp.domain.ledger import LedgerStatus
from cashapp.domain.money import money_eq
from cashapp.domain.principal import Permission, Principal
from cashapp.domain.stages import ItemState, Stage
from cashapp.domain.status import LineStatus, PaymentStatus
from cashapp.domain.work_item import HistoryAction
from cashapp.integrations.fusion.client import FusionClient
from cashapp.integrations.fusion.errors import FusionError
from cashapp.integrations.fusion.models import UnapplyRequest
from cashapp.services.actor import actor_fields
from cashapp.services.history import HistoryEntry, record_history
from cashapp.services.locking import LockNotHeld, LockService
from cashapp.services.payment_status import derive_payment_status

logger = logging.getLogger(__name__)

# UNVERIFIED: the status Fusion reports for a live application (s05 FusionApplication.status).
ACTIVE_APPLICATION_STATUS: Final = "APP"

MAX_REASON_LENGTH: Final = 1000


@dataclass(frozen=True, slots=True)
class ReversalResult:
    item_id: int
    ledger_id: int
    application_id: int
    receipt_id: int
    receipt_number: str
    amount: Decimal
    reversal_gl_date: date
    item_stage: Stage
    item_state: ItemState
    payment_status: PaymentStatus


class ReversalError(Exception):
    status_code: ClassVar[int] = 400
    code: ClassVar[str] = "reversal_error"
    error_code: ClassVar[ErrorCode | None] = None

    def __init__(self, message: str, *, details: Sequence[Mapping[str, Any]] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.details: list[dict[str, Any]] = [dict(d) for d in details]


class ReversalForbidden(ReversalError):  # noqa: N818
    status_code = 403
    code = "forbidden"


class ReasonRequired(ReversalError):  # noqa: N818
    status_code = 422
    code = "reason_required"


class UnverifiedContract(ReversalError):  # noqa: N818
    status_code = 503
    code = "unverified_contract"


class ItemNotFound(ReversalError):  # noqa: N818
    status_code = 404
    code = "item_not_found"


class ReversalLockNotHeld(ReversalError):  # noqa: N818
    status_code = 409
    code = "lock_not_held"


class NotSystemApplication(ReversalError):  # noqa: N818
    status_code = 409
    code = "not_system_application"


class ConfirmationMismatch(ReversalError):  # noqa: N818
    status_code = 422
    code = "confirmation_mismatch"


class ChangedOutsideCashApp(ReversalError):  # noqa: N818
    status_code = 409
    code = "changed_outside_cashapp"
    error_code = ErrorCode.REVERSAL_FAILED


class ReversalFusionFailed(ReversalError):  # noqa: N818
    status_code = 502
    code = "reversal_failed"
    error_code = ErrorCode.REVERSAL_FAILED


class ReversalWritesDisabled(ReversalFusionFailed):
    """Fusion writes are switched off in this environment: 503, same code."""

    status_code = 503


def reversal_gl_date(original_accounting_date: date, today: date) -> date:
    """UNVERIFIED rule: on or after the application's GL date, and not in the past."""
    return max(original_accounting_date, today)


def _accounting_date(request: Mapping[str, Any] | None) -> date | None:
    raw = request.get("accounting_date") if request is not None else None
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _request_payload(request: UnapplyRequest) -> dict[str, Any]:
    data = dataclasses.asdict(request)
    data["reversal_gl_date"] = request.reversal_gl_date.isoformat()
    return data


class ReversalService:
    def __init__(
        self, fusion: FusionClient, *, unapply_verified: bool, clock: Clock | None = None
    ) -> None:
        self._fusion = fusion
        self._unapply_verified = unapply_verified
        self._clock: Clock = clock or SystemClock()

    async def reverse(
        self,
        uow: UnitOfWork,
        *,
        item_id: int,
        ledger_id: int,
        principal: Principal,
        reason: str,
        confirm_receipt_number: str,
    ) -> ReversalResult:
        if principal.is_system or not principal.can(Permission.APPLY_REVERSE):
            raise ReversalForbidden(
                f"Reversing an application requires {Permission.APPLY_REVERSE.value}",
                details=[{"permission": Permission.APPLY_REVERSE.value}],
            )
        cleaned = reason.strip()
        if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
            raise ReasonRequired(
                f"A reason of 1 to {MAX_REASON_LENGTH} characters is required to reverse"
            )
        if not self._unapply_verified:
            raise UnverifiedContract(
                "The Fusion unapply contract has not been confirmed on a live pod"
            )

        item = await uow.work_items.get_for_update(item_id, skip_locked=False)
        if item is None:
            raise ItemNotFound(f"Item {item_id} not found")
        now = self._clock.now()
        try:
            LockService.assert_held_by(item, principal, now)
        except LockNotHeld as exc:
            raise ReversalLockNotHeld("You do not hold the lock on this item") from exc

        ledger_repo = uow.repo(ApplicationLedgerRepository)
        row = await ledger_repo.get(ledger_id)
        if (
            row is None
            or row.work_item_id != item_id
            or row.status is not LedgerStatus.APPLIED
            or row.fusion_application_id is None
        ):
            raise NotSystemApplication(
                "Only applications made by this system and still applied can be reversed"
            )
        application_id = row.fusion_application_id

        receipt = await self._fusion.get_receipt(row.receipt_id)
        if confirm_receipt_number.strip() != receipt.receipt_number.strip():
            raise ConfirmationMismatch("The receipt number typed does not match the receipt")

        applications = await self._fusion.list_receipt_applications(row.receipt_id)
        current = next((a for a in applications if a.application_id == application_id), None)
        if (
            current is None
            or current.status != ACTIVE_APPLICATION_STATUS
            or current.customer_trx_id != row.customer_trx_id
            or not money_eq(current.amount_applied, row.amount)
        ):
            raise ChangedOutsideCashApp(
                "The application was changed outside CashApp",
                details=[
                    {
                        "application_id": application_id,
                        "ledger_amount": str(row.amount),
                        "fusion_amount": (
                            str(current.amount_applied) if current is not None else None
                        ),
                        "fusion_status": current.status if current is not None else None,
                    }
                ],
            )

        original = _accounting_date(row.request) or current.apply_date
        request = UnapplyRequest(
            receipt_id=row.receipt_id,
            application_id=application_id,
            reversal_gl_date=reversal_gl_date(original, now.date()),
            reason=cleaned,
        )
        try:
            result = await self._fusion.unapply_receipt(request)
        except FusionError as exc:
            logger.error("Unapply failed item=%s ledger=%s code=%s", item_id, ledger_id, exc.code)
            failure_type = (
                ReversalWritesDisabled
                if exc.code is ErrorCode.FUSION_WRITE_DISABLED
                else ReversalFusionFailed
            )
            raise failure_type(
                f"Fusion could not reverse the application: {exc.message}",
                details=[
                    {
                        "error_code": exc.code.value,
                        "fusion_code": exc.fusion_code,
                        "message": exc.message,
                    }
                ],
            ) from exc
        if not result.ok:
            fault = result.fault
            logger.error("Unapply refused item=%s ledger=%s", item_id, ledger_id)
            raise ReversalFusionFailed(
                "Fusion refused to reverse the application",
                details=[
                    {
                        "error_code": fault.code.value if fault is not None else None,
                        "fusion_code": fault.fusion_code if fault is not None else None,
                        "message": fault.message if fault is not None else None,
                    }
                ],
            )

        await ledger_repo.mark(
            row,
            LedgerStatus.REVERSED,
            reversed_at=now,
            reversed_by=principal.subject,
            reversal_reason=cleaned,
        )
        await uow.repo(LineResultRepository).upsert(
            item_id,
            row.line_no,
            line_status=LineStatus.ALLOCATION_REVERSED,
            reason=f"Reversed by {principal.display_name}: {cleaned}"[:MAX_REASON_LENGTH],
        )
        before = item.payment_status
        status = await derive_payment_status(uow, item)
        await uow.repo(ReservationRepository).release(
            item_id, f"application {row.id} reversed", now=now
        )

        from_stage, from_state = item.stage, item.state
        actor = actor_fields(principal)
        await record_history(
            uow,
            item_id,
            HistoryEntry(
                action=HistoryAction.HUMAN_ACTION,
                **actor,
                from_stage=from_stage,
                to_stage=Stage.MATCH_RECEIPT,
                from_state=from_state,
                to_state=ItemState.ESCALATED,
                reasoning=cleaned,
                payload={
                    "event": "reverse_application",
                    "ledger_id": row.id,
                    "application_id": application_id,
                    "receipt_id": row.receipt_id,
                    "receipt_number": receipt.receipt_number,
                    "customer_trx_id": row.customer_trx_id,
                    "amount": row.amount,
                    "line_no": row.line_no,
                    "payment_status_before": before.value if before is not None else None,
                    "payment_status_after": status.value,
                },
            ),
            clock=self._clock,
        )
        await record_history(
            uow,
            item_id,
            HistoryEntry(
                action=HistoryAction.FUSION_WRITE,
                **actor,
                reasoning=cleaned,
                payload={
                    "operation": "unapply_receipt",
                    "request": _request_payload(request),
                    "messages": [
                        {"code": m.code, "severity": m.severity, "text": m.text}
                        for m in result.raw_messages
                    ],
                },
            ),
            clock=self._clock,
        )
        await uow.work_items.update(
            item,
            stage=Stage.MATCH_RECEIPT,
            state=ItemState.ESCALATED,
            last_error_code=None,
            last_error_detail=None,
            escalation_summary=f"Application reversed by {principal.display_name}: {cleaned}",
            payment_status=status,
        )
        return ReversalResult(
            item_id=item_id,
            ledger_id=row.id,
            application_id=application_id,
            receipt_id=row.receipt_id,
            receipt_number=receipt.receipt_number,
            amount=row.amount,
            reversal_gl_date=request.reversal_gl_date,
            item_stage=Stage.MATCH_RECEIPT,
            item_state=ItemState.ESCALATED,
            payment_status=status,
        )
