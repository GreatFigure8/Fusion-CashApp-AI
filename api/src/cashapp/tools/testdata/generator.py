"""Create a scenario's invoices, credit memos and unapplied receipts in Fusion.

All traffic goes through the one `FusionClient`. There is no retry and no rollback: if a call fails
midway the error carries what was already created, and the CLI still writes the manifest so
`cleanup` can find it. Nothing is ever deleted automatically.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from typing import Any, Literal

from cashapp.domain.clock import Clock, SystemClock
from cashapp.domain.config_keys import FusionTestData
from cashapp.domain.error_codes import ErrorCode
from cashapp.integrations.fusion import ApplyRequest, FusionClient, FusionError, accounting_date_for
from cashapp.tools.testdata import payloads
from cashapp.tools.testdata.models import CreatedRecord, GeneratedData, ScenarioPlan
from cashapp.tools.testdata.tagging import validate_tag


class GenerationError(Exception):
    """Generation stopped midway; `partial` holds everything created before the failure."""

    def __init__(self, message: str, *, partial: GeneratedData, cause: Exception) -> None:
        super().__init__(message)
        self.partial = partial
        self.cause = cause


def _created_id(response: Mapping[str, Any], key: str, what: str) -> int:
    value = response.get(key)
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise FusionError(ErrorCode.FUSION_FAULT, f"{what}: response has no {key}", retryable=False)
    try:
        return int(value)
    except ValueError as exc:
        raise FusionError(
            ErrorCode.FUSION_FAULT, f"{what}: response {key} is not an id", retryable=False
        ) from exc


async def _create_transaction(
    fusion: FusionClient,
    *,
    resource: str,
    body: Mapping[str, Any],
    number: str,
    kind: Literal["INVOICE", "CREDIT_MEMO"],
    records: list[CreatedRecord],
) -> None:
    response = await fusion.rest_post(resource, body)
    fusion_id = _created_id(response, "CustomerTransactionId", number)
    records.append(CreatedRecord(kind=kind, number=number, fusion_id=fusion_id))
    await fusion.rest_post(payloads.complete_path(resource, fusion_id), {})


async def _build(
    plan: ScenarioPlan,
    fusion: FusionClient,
    *,
    tag: str,
    defaults: FusionTestData,
    bill_to_site: str | None,
    today: date,
    records: list[CreatedRecord],
) -> None:
    customer = plan.customer_account
    for invoice in plan.invoices:
        await _create_transaction(
            fusion,
            resource=payloads.PATH_INVOICES,
            body=payloads.invoice_payload(
                invoice,
                tag=tag,
                customer_account=customer,
                defaults=defaults,
                bill_to_site=bill_to_site,
            ),
            number=invoice.number,
            kind="INVOICE",
            records=records,
        )
    for memo in plan.credit_memos:
        await _create_transaction(
            fusion,
            resource=payloads.PATH_CREDIT_MEMOS,
            body=payloads.credit_memo_payload(
                memo,
                tag=tag,
                customer_account=customer,
                defaults=defaults,
                bill_to_site=bill_to_site,
            ),
            number=memo.number,
            kind="CREDIT_MEMO",
            records=records,
        )
    for receipt in plan.receipts:
        response = await fusion.rest_post(
            payloads.PATH_RECEIPTS,
            payloads.receipt_payload(
                receipt, tag=tag, customer_account=customer, defaults=defaults
            ),
        )
        records.append(
            CreatedRecord(
                kind="RECEIPT",
                number=receipt.number,
                fusion_id=_created_id(response, "StandardReceiptId", receipt.number),
            )
        )
    await _pre_apply(plan, fusion, today=today, records=records)


async def _pre_apply(
    plan: ScenarioPlan, fusion: FusionClient, *, today: date, records: list[CreatedRecord]
) -> None:
    if not plan.pre_applications:
        return
    ids = {r.number: r.fusion_id for r in records if r.fusion_id is not None}
    as_of = plan.params.as_of
    for application in plan.pre_applications:
        result = await fusion.apply_receipt(
            ApplyRequest(
                receipt_id=ids[application.receipt_number],
                customer_trx_id=ids[application.transaction_number],
                amount_applied=application.amount,
                receipt_currency=plan.params.currency,
                application_date=as_of,
                accounting_date=accounting_date_for(as_of, today),
            )
        )
        if not result.ok:
            code = result.fault.code if result.fault is not None else ErrorCode.FUSION_FAULT
            message = result.fault.message if result.fault is not None else "apply failed"
            raise FusionError(code, f"pre-application failed: {message}", retryable=False)
        records.append(
            CreatedRecord(
                kind="APPLICATION",
                number=f"{application.receipt_number}>{application.transaction_number}",
                fusion_id=result.application_id,
            )
        )


async def generate(
    plan: ScenarioPlan,
    fusion: FusionClient,
    *,
    tag: str,
    defaults: FusionTestData,
    bill_to_site: str | None = None,
    guard: Callable[[], None] | None = None,
    today: date | None = None,
    clock: Clock = SystemClock(),  # noqa: B008 - stateless clock
) -> GeneratedData:
    tag = validate_tag(tag)
    if tag != plan.tag:
        raise ValueError(f"tag {tag} does not match the plan's tag {plan.tag}")
    if guard is not None:
        guard()
    created_at = clock.now()
    records: list[CreatedRecord] = []

    def snapshot() -> GeneratedData:
        return GeneratedData(
            tag=tag,
            scenario=plan.scenario,
            pod_name=fusion.pod_name,
            created_at=created_at,
            records=list(records),
        )

    try:
        await _build(
            plan,
            fusion,
            tag=tag,
            defaults=defaults,
            bill_to_site=bill_to_site,
            today=today or created_at.date(),
            records=records,
        )
    except FusionError as exc:
        raise GenerationError(
            f"generation of {plan.scenario} stopped after {len(records)} records: {exc}",
            partial=snapshot(),
            cause=exc,
        ) from exc
    return snapshot()
